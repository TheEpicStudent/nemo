import argparse
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations

from dotenv import load_dotenv
from psycopg import errors, sql

from ingest.member_links import catalogue, scoring
from jobs.link_verdicts import VERDICTS
from lib.db import connect
from lib.graph import components
from lib.mailbox import mailbox, staff_domain
from lib.paths import ENV_FILE

LINKS = "fd.member_link"
TABLE = re.compile(r"^([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)$")
BAND_NAMES = ("certain", "strong", "worth a look")
RIGHT = ("same_person",)
WRONG = ("different_people", "household")

BANDS_SQL = """
SELECT count(*) FILTER (WHERE score >= %(certain)s),
       count(*) FILTER (WHERE score >= %(strong)s AND score < %(certain)s),
       count(*) FILTER (WHERE score < %(strong)s)
FROM {links}
"""

VERDICTS_SQL = """
SELECT v.a_user_id, v.b_user_id, v.verdict, l.score
FROM fd.member_link_verdict v
LEFT JOIN {links} l ON l.a_user_id = v.a_user_id AND l.b_user_id = v.b_user_id
"""

AMONG_SQL = """
SELECT a_user_id, b_user_id, score
FROM {links}
WHERE a_user_id = ANY(%(ids)s) AND b_user_id = ANY(%(ids)s)
"""

MAILBOXES_SQL = """
SELECT user_id, email FROM fd.member_identity
WHERE email IS NOT NULL AND position('@' IN email) > 0
"""


def links_table(name):
    match = TABLE.match(name or "")
    if not match:
        raise ValueError(f"{name!r} is not a schema.table name")
    return sql.Identifier(*match.groups())


def band_of(score, thresholds):
    if score >= thresholds["certain"]:
        return "certain"
    if score >= thresholds["strong"]:
        return "strong"
    return "worth a look"


def alias_pairs(rows, staff):
    boxes = defaultdict(set)
    for user_id, email in rows:
        box = mailbox(email)
        if box and not staff_domain(box.rpartition("@")[2], staff):
            boxes[box].add(user_id)
    return {pair for users in boxes.values() for pair in combinations(sorted(users), 2)}


def hub(person, pairs):
    counts = Counter(one for pair in pairs for one in pair if one in person)
    return min(person, key=lambda one: (-counts[one], one))


def together(person, links):
    internal_links = [(a, b) for a, b in links if a in person and b in person]
    groups = components(internal_links)
    return len(groups[0]) if groups else 0


def band_summary(pairs, scores, thresholds):
    bands = Counter(band_of(scores[pair], thresholds) for pair in pairs if pair in scores)
    return {"pairs": len(pairs), "linked": sum(bands.values()), "bands": bands}


def labelled(rows):
    return [(None if score is None else float(score), verdict in RIGHT)
            for _a, _b, verdict, score in rows if verdict in RIGHT + WRONG]


def suggest_cutoffs(pairs, targets):
    right = sum(1 for _score, good in pairs if good)
    wrong = len(pairs) - right
    minimum = targets["least_verdicts"]
    summary = {"right": right, "wrong": wrong, "enough": right >= minimum and wrong >= minimum, "cuts": {}}
    if not summary["enough"]:
        return summary
    scored = sorted({score for score, _good in pairs if score is not None})
    for name, target in targets["precision"].items():
        for cut in scored:
            above = [good for score, good in pairs if score is not None and score >= cut]
            precision = sum(above) / len(above)
            if precision >= target:
                summary["cuts"][name] = {"cut": cut, "precision": precision, "recall": sum(above) / right}
                break
    return summary


def measure(conn, links_name=LINKS):
    thresholds = scoring()
    config = catalogue()
    staff = config.get("staff_domains", [])
    targets = config.get("band_targets")
    links = links_table(links_name)

    def query(text, params=None):
        return conn.execute(sql.SQL(text).format(links=links), params).fetchall()

    banded = query(BANDS_SQL, thresholds)[0]
    rows = query(VERDICTS_SQL)

    by_verdict = defaultdict(set)
    scores = {}
    for a, b, verdict, score in rows:
        by_verdict[verdict].add((a, b))
        if score is not None:
            scores[(a, b)] = float(score)
    verdicts = {verdict: band_summary(by_verdict[verdict], scores, thresholds) for verdict in VERDICTS}

    confirmed = by_verdict["same_person"]
    groups = components(confirmed)
    accounts = sorted(set().union(*groups)) if groups else []
    account_links = query(AMONG_SQL, {"ids": accounts}) if accounts else []
    all_pairs = [(a, b) for a, b, _score in account_links]
    strong_pairs = [(a, b) for a, b, score in account_links if float(score) >= thresholds["strong"]]
    confirmed_people = [
        {"hub": hub(group, confirmed), "accounts": len(group),
         "together": together(group, all_pairs), "strong_together": together(group, strong_pairs)}
        for group in groups
    ]

    aliases = alias_pairs(conn.execute(MAILBOXES_SQL).fetchall(), staff)
    alias_ids = sorted({one for pair in aliases for one in pair})
    alias_links = query(AMONG_SQL, {"ids": alias_ids}) if alias_ids else []
    alias_scores = {(a, b): float(score) for a, b, score in alias_links if (a, b) in aliases}

    return {
        "links": links_name,
        "bands": dict(zip(BAND_NAMES, banded, strict=True)),
        "verdicts": verdicts,
        "people": confirmed_people,
        "aliases": band_summary(aliases, alias_scores, thresholds),
        "marks": thresholds,
        "cutoffs": suggest_cutoffs(labelled(rows), targets) if targets else None,
    }


def share(part, total):
    return f"{round(100 * part / total)}%" if total else "n/a"


def band_line(bands):
    return ", ".join(f"{name} {bands.get(name, 0):,}" for name in BAND_NAMES)


def render(result):
    bands = result["bands"]
    lines = [f"links in {result['links']}: {sum(bands.values()):,} ({band_line(bands)})", ""]

    lines.append("verdict pairs the finder links")
    for verdict, one in result["verdicts"].items():
        lines.append(f"  {verdict:<17} {one['linked']:>6,} of {one['pairs']:<6,} "
                     f"{share(one['linked'], one['pairs']):>4}  {band_line(one['bands'])}")
    lines.append("")

    confirmed = result["people"]
    total = sum(one["accounts"] for one in confirmed)
    linked = sum(one["together"] for one in confirmed)
    strong = sum(one["strong_together"] for one in confirmed)
    lines.append(f"people confirmed by same_person verdicts: {len(confirmed):,}, {total:,} accounts")
    for one in confirmed:
        lines.append(f"  {one['hub']:<13} {one['accounts']:>4} accounts  "
                     f"{one['together']:>4} linked together  "
                     f"{one['strong_together']:>4} at strong or above")
    if confirmed:
        lines.append(f"  {'all':<13} {total:>4} accounts  {linked:>4} linked together "
                     f"({share(linked, total)})  {strong:>4} at strong or above "
                     f"({share(strong, total)})")
    lines.append("")

    aliases = result["aliases"]
    lines.append(f"email aliases outside staff domains: {aliases['linked']:,} of "
                 f"{aliases['pairs']:,} linked ({share(aliases['linked'], aliases['pairs'])}): "
                 f"{band_line(aliases['bands'])}")

    cutoffs = result.get("cutoffs")
    if cutoffs is None:
        return lines
    lines.append("")
    lines.append(f"bands from verdicts: {cutoffs['right']:,} same person, "
                 f"{cutoffs['wrong']:,} different people or household")
    if not cutoffs["enough"]:
        lines.append("  not enough verdicts to suggest cutoffs yet")
        return lines
    for name in ("floor", "strong", "certain"):
        current = result["marks"][name]
        one = cutoffs["cuts"].get(name)
        if one is None:
            lines.append(f"  {name:<8} now {current:g}, no score reaches the precision asked for")
            continue
        lines.append(f"  {name:<8} now {current:g}, suggested {one['cut']:g} "
                     f"(precision {share(one['precision'], 1)}, recall {share(one['recall'], 1)})")
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(description="score the alt finder against link verdicts")
    parser.add_argument("--links", default=LINKS,
                        help="schema.table holding a_user_id < b_user_id and score, like fd.member_link")
    parser.add_argument("--dsn", help="Postgres DSN to use instead of the environment configuration")
    args = parser.parse_args(argv)
    load_dotenv(ENV_FILE)
    try:
        links_table(args.links)
    except ValueError as error:
        print(f"check-links: {error}", file=sys.stderr)
        return 2
    try:
        with connect(args.dsn) as conn:
            conn.read_only = True
            result = measure(conn, args.links)
    except (errors.UndefinedTable, errors.UndefinedColumn) as error:
        print(f"check-links: {str(error).splitlines()[0]}", file=sys.stderr)
        return 2
    print("\n".join(render(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
