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
FOUND = ("certain", "strong")
UNLINKED = "not linked"
RIGHT = ("same_person",)
WRONG = ("different_people", "household")
MACHINES = ["USLACKBOT", "U09ULFV88KU"]
BANNED_AGAIN_DAYS = 30
HOME_CROWD = 8
EXIT_CROWD = 10

BANDS_SQL = """
SELECT count(*) FILTER (WHERE score >= %(certain)s),
       count(*) FILTER (WHERE score >= %(strong)s AND score < %(certain)s),
       count(*) FILTER (WHERE score < %(strong)s)
FROM {links}
"""

VERDICTS_SQL = """
SELECT v.a_user_id, v.b_user_id, v.verdict, l.score, l.top_signal
FROM fd.member_link_verdict v
LEFT JOIN {links} l ON l.a_user_id = v.a_user_id AND l.b_user_id = v.b_user_id
"""

AMONG_SQL = """
SELECT a_user_id, b_user_id, score
FROM {links}
WHERE a_user_id = ANY(%(ids)s) AND b_user_id = ANY(%(ids)s)
"""

POST_BAN_SQL = """
WITH off AS MATERIALIZED (
    SELECT DISTINCT ON (d.entity_id) d.entity_id AS user_id, d.at AS off_at
    FROM slack.audit_event d
    WHERE d.action = 'user_deactivated' AND NOT d.ours AND d.entity_id IS NOT NULL
      AND d.actor_id <> d.entity_id AND d.actor_id <> ALL(%(machines)s)
    ORDER BY d.entity_id, d.at DESC
),
banned AS MATERIALIZED (
    SELECT o.user_id, o.off_at, j.joined_at
    FROM off o
    LEFT JOIN fd.member_joins j ON j.user_id = o.user_id
    WHERE NOT EXISTS (SELECT 1 FROM slack.audit_event r
                      WHERE r.entity_id = o.user_id AND r.action = 'user_reactivated' AND r.at > o.off_at)
),
later AS MATERIALIZED (
    SELECT user_id, joined_at FROM banned
    WHERE off_at <= joined_at + make_interval(days => %(within)s)
),
inbox AS (
    SELECT b.user_id AS banned, l.user_id AS later, 'inbox' AS evidence
    FROM banned b
    JOIN fd.member_trait tb ON tb.user_id = b.user_id AND tb.kind = 'mailbox'
    JOIN fd.member_trait tl ON tl.kind = 'mailbox' AND tl.value = tb.value AND tl.user_id <> b.user_id
    JOIN later l ON l.user_id = tl.user_id AND l.joined_at > b.off_at
),
seen AS MATERIALIZED (
    SELECT DISTINCT user_id, ip, ua_id, kind FROM (
        SELECT e.user_id, e.ip, e.ua_id,
               CASE WHEN n.class IN ('vpn', 'hosting') THEN 'exit'
                    WHEN n.class IN ('rotating', 'tor') THEN NULL
                    WHEN EXISTS (SELECT 1 FROM fd.shared_ip s WHERE s.ip = e.ip) THEN NULL
                    ELSE 'home' END AS kind
        FROM fd.login_event e
        LEFT JOIN fd.ip_network n ON n.ip_prefix = e.ip_prefix
        WHERE e.ip IS NOT NULL AND e.user_id IN (SELECT user_id FROM banned)
    ) classed
    WHERE kind IS NOT NULL
),
address AS MATERIALIZED (
    SELECT DISTINCT b.user_id AS banned, sl.user_id AS later, sb.ip, sb.kind
    FROM banned b
    JOIN seen sb ON sb.user_id = b.user_id
    JOIN seen sl ON sl.ip = sb.ip AND sl.kind = sb.kind AND sl.user_id <> sb.user_id
                AND (sb.kind = 'home' OR sl.ua_id = sb.ua_id)
    JOIN later l ON l.user_id = sl.user_id AND l.joined_at > b.off_at
),
crowd AS (
    SELECT a.ip, count(DISTINCT e.user_id) AS people
    FROM (SELECT DISTINCT ip FROM address) a
    JOIN fd.login_event e ON e.ip = a.ip
    GROUP BY a.ip
),
shared AS (
    SELECT banned, later, evidence FROM inbox
    UNION
    SELECT a.banned, a.later, CASE a.kind WHEN 'home' THEN 'home address' ELSE 'VPN exit' END
    FROM address a
    JOIN crowd c ON c.ip = a.ip
    WHERE c.people <= CASE a.kind WHEN 'home' THEN %(home)s ELSE %(exit)s END
),
pair AS (
    SELECT least(banned, later) AS a_user_id, greatest(banned, later) AS b_user_id,
           array_agg(DISTINCT evidence ORDER BY evidence) AS evidence
    FROM shared
    GROUP BY 1, 2
)
SELECT p.a_user_id, p.b_user_id, l.score, l.top_signal, p.evidence
FROM pair p
LEFT JOIN {links} l ON l.a_user_id = p.a_user_id AND l.b_user_id = p.b_user_id
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
            for _a, _b, verdict, score, *_rest in rows if verdict in RIGHT + WRONG]


def recall(items, thresholds):
    bands = Counter()
    signal_found, signal_linked = Counter(), Counter()
    evidence_found, evidence_pairs = Counter(), Counter()
    for score, top_signal, shared in items:
        band = UNLINKED if score is None else band_of(float(score), thresholds)
        found = band in FOUND
        bands[band] += 1
        if top_signal:
            signal_linked[top_signal] += 1
            signal_found[top_signal] += found
        for name in shared:
            evidence_pairs[name] += 1
            evidence_found[name] += found
    return {"pairs": len(items), "found": sum(bands[band] for band in FOUND), "bands": bands,
            "signals": {name: (signal_found[name], total) for name, total in signal_linked.items()},
            "evidence": {name: (evidence_found[name], total) for name, total in evidence_pairs.items()}}


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
    for a, b, verdict, score, _top_signal in rows:
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

    post_ban = query(POST_BAN_SQL, {"machines": MACHINES, "within": BANNED_AGAIN_DAYS,
                                    "home": HOME_CROWD, "exit": EXIT_CROWD})
    same_person = [(score, top_signal, ()) for _a, _b, verdict, score, top_signal in rows
                   if verdict == "same_person"]

    return {
        "links": links_name,
        "bands": dict(zip(BAND_NAMES, banded, strict=True)),
        "recall": {
            "post-ban": recall([(score, top_signal, evidence)
                                for _a, _b, score, top_signal, evidence in post_ban], thresholds),
            "same person": recall(same_person, thresholds),
        },
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


def tally(counts):
    ordered = sorted(counts.items(), key=lambda item: (-item[1][1], item[0]))
    return ", ".join(f"{name} {found:,} of {total:,}" for name, (found, total) in ordered)


def recall_lines(recalls):
    lines = [f"recall at strong or above (post-ban: banned again within {BANNED_AGAIN_DAYS} days, "
             f"sharing an inbox, a home address held by {HOME_CROWD} or fewer, "
             f"or a VPN exit held by {EXIT_CROWD} or fewer on one build)"]
    for name, one in recalls.items():
        lines.append(f"  {name:<17} {one['found']:>6,} of {one['pairs']:<6,} "
                     f"{share(one['found'], one['pairs']):>4}  {band_line(one['bands'])}, "
                     f"{UNLINKED} {one['bands'].get(UNLINKED, 0):,}")
        if one["evidence"]:
            lines.append(f"    by what they share  {tally(one['evidence'])}")
        if one["signals"]:
            lines.append(f"    by top signal       {tally(one['signals'])}")
    lines.append("")
    return lines


def render(result):
    bands = result["bands"]
    lines = [f"links in {result['links']}: {sum(bands.values()):,} ({band_line(bands)})", ""]

    if result.get("recall"):
        lines.extend(recall_lines(result["recall"]))

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
                        help="schema.table holding a_user_id < b_user_id, score and top_signal, like fd.member_link")
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
