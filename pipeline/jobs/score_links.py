import argparse
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations

from dotenv import load_dotenv
from psycopg import errors, sql

from ingest.member_links import BOT_USER_IDS, catalogue, scoring
from jobs.link_verdicts import VERDICTS
from lib.db import connect
from lib.graph import components
from lib.mailbox import mailbox, staff_domain
from lib.paths import ENV_FILE

LINKS = "fd.member_link"
TABLE = re.compile(r"^([a-z_][a-z0-9_]*)\.([a-z_][a-z0-9_]*)$")
BAND_NAMES = ("certain", "strong", "worth a look")
RECALLED_BANDS = ("certain", "strong")
UNLINKED = "not linked"
RIGHT = ("same_person",)
WRONG = ("different_people",)
REBAN_WINDOW_DAYS = 30
HOME_IP_MAX_USERS = 8
VPN_IP_MAX_USERS = 10
LIVE_VARIANT = "live"
SHADOW_LINKS = "fd.member_link_shadow"
VARIANT_NAME = re.compile(r"^[a-z0-9_]{1,40}$")
BAND_DISPLAY = {"certain": "certain", "strong": "strong", "weak": "worth a look"}
BAND_ORDER = {"weak": 1, "strong": 2, "certain": 3}
SAMPLE_BANDS = ("certain", "strong", "weak")
SAMPLE_TARGET_KEYS = {"certain": "certain", "strong": "strong", "weak": "floor"}

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
WITH deactivation AS MATERIALIZED (
    SELECT DISTINCT ON (d.entity_id) d.entity_id AS user_id, d.at AS deactivated_at
    FROM slack.audit_event d
    WHERE d.action = 'user_deactivated' AND NOT d.ours AND d.entity_id IS NOT NULL
      AND d.actor_id <> d.entity_id AND d.actor_id <> ALL(%(bot_user_ids)s)
    ORDER BY d.entity_id, d.at DESC
),
banned_account AS MATERIALIZED (
    SELECT d.user_id, d.deactivated_at, j.joined_at
    FROM deactivation d
    LEFT JOIN fd.member_joins j ON j.user_id = d.user_id
    WHERE NOT EXISTS (SELECT 1 FROM slack.audit_event r
                      WHERE r.entity_id = d.user_id AND r.action = 'user_reactivated'
                        AND r.at > d.deactivated_at)
),
rebanned_account AS MATERIALIZED (
    SELECT user_id, joined_at FROM banned_account
    WHERE deactivated_at <= joined_at + make_interval(days => %(reban_window_days)s)
),
mailbox_pair AS (
    SELECT b.user_id AS banned_user_id, r.user_id AS rebanned_user_id, 'inbox' AS evidence
    FROM banned_account b
    JOIN fd.member_trait tb ON tb.user_id = b.user_id AND tb.kind = 'mailbox'
    JOIN fd.member_trait tr ON tr.kind = 'mailbox' AND tr.value = tb.value AND tr.user_id <> b.user_id
    JOIN rebanned_account r ON r.user_id = tr.user_id AND r.joined_at > b.deactivated_at
),
ip_use AS MATERIALIZED (
    SELECT DISTINCT user_id, ip, ua_id, ip_class FROM (
        SELECT e.user_id, e.ip, e.ua_id,
               CASE WHEN n.class IN ('vpn', 'hosting') THEN 'vpn'
                    WHEN n.class IN ('rotating', 'tor') THEN NULL
                    WHEN EXISTS (SELECT 1 FROM fd.shared_ip s WHERE s.ip = e.ip) THEN NULL
                    ELSE 'home' END AS ip_class
        FROM fd.login_event e
        LEFT JOIN fd.ip_network n ON n.ip_prefix = e.ip_prefix
        WHERE e.ip IS NOT NULL AND e.user_id IN (SELECT user_id FROM banned_account)
    ) classified
    WHERE ip_class IS NOT NULL
),
ip_pair AS MATERIALIZED (
    SELECT DISTINCT b.user_id AS banned_user_id, ur.user_id AS rebanned_user_id, ub.ip, ub.ip_class
    FROM banned_account b
    JOIN ip_use ub ON ub.user_id = b.user_id
    JOIN ip_use ur ON ur.ip = ub.ip AND ur.ip_class = ub.ip_class AND ur.user_id <> ub.user_id
                  AND (ub.ip_class = 'home' OR ur.ua_id = ub.ua_id)
    JOIN rebanned_account r ON r.user_id = ur.user_id AND r.joined_at > b.deactivated_at
),
ip_user_count AS (
    SELECT p.ip, count(DISTINCT e.user_id) AS user_count
    FROM (SELECT DISTINCT ip FROM ip_pair) p
    JOIN fd.login_event e ON e.ip = p.ip
    GROUP BY p.ip
),
evidence_pair AS (
    SELECT banned_user_id, rebanned_user_id, evidence FROM mailbox_pair
    UNION
    SELECT p.banned_user_id, p.rebanned_user_id,
           CASE p.ip_class WHEN 'home' THEN 'home address' ELSE 'VPN exit' END
    FROM ip_pair p
    JOIN ip_user_count c ON c.ip = p.ip
    WHERE c.user_count <= CASE p.ip_class WHEN 'home' THEN %(home_ip_max_users)s
                                          ELSE %(vpn_ip_max_users)s END
),
post_ban_pair AS (
    SELECT least(banned_user_id, rebanned_user_id) AS a_user_id,
           greatest(banned_user_id, rebanned_user_id) AS b_user_id,
           array_agg(DISTINCT evidence ORDER BY evidence) AS evidence
    FROM evidence_pair
    GROUP BY 1, 2
)
SELECT p.a_user_id, p.b_user_id, l.score, l.top_signal, p.evidence
FROM post_ban_pair p
LEFT JOIN {links} l ON l.a_user_id = p.a_user_id AND l.b_user_id = p.b_user_id
"""

DRAW_SQL = """
WITH banded AS (
    SELECT l.a_user_id, l.b_user_id, l.score, l.top_signal,
           CASE WHEN l.score >= %(certain)s THEN 'certain'
                WHEN l.score >= %(strong)s THEN 'strong'
                ELSE 'weak' END AS band
    FROM {links} l
    WHERE NOT EXISTS (SELECT 1 FROM fd.link_sample s
                      WHERE s.variant = %(variant)s
                        AND s.a_user_id = l.a_user_id AND s.b_user_id = l.b_user_id)
),
stratum_ranked AS (
    SELECT b.*,
           row_number() OVER (PARTITION BY b.band, b.top_signal ORDER BY random())::numeric
               / count(*) OVER (PARTITION BY b.band, b.top_signal) AS stratum_position
    FROM banded b
    WHERE b.band = ANY(%(bands)s)
),
band_ranked AS (
    SELECT r.*, row_number() OVER (PARTITION BY r.band ORDER BY r.stratum_position, random()) AS band_rank
    FROM stratum_ranked r
)
INSERT INTO fd.link_sample (variant, a_user_id, b_user_id, band, top_signal, score)
SELECT %(variant)s, a_user_id, b_user_id, band, top_signal, score
FROM band_ranked
WHERE band_rank <= %(per_band)s
RETURNING band
"""

SAMPLE_PRECISION_SQL = """
SELECT s.band, count(*) AS drawn,
       count(*) FILTER (WHERE v.verdict = ANY(%(right)s)) AS right_count,
       count(*) FILTER (WHERE v.verdict = ANY(%(wrong)s)) AS wrong_count
FROM fd.link_sample s
LEFT JOIN fd.member_link_verdict v ON v.a_user_id = s.a_user_id AND v.b_user_id = s.b_user_id
WHERE s.variant = %(variant)s
GROUP BY s.band
"""

BAND_SHIFT_SQL = """
SELECT v.band AS variant_band, l.band AS live_band, count(*)
FROM (SELECT a_user_id, b_user_id,
             CASE WHEN score >= %(certain)s THEN 'certain' WHEN score >= %(strong)s THEN 'strong'
                  ELSE 'weak' END AS band
      FROM {links}) v
FULL JOIN (SELECT a_user_id, b_user_id,
                  CASE WHEN score >= %(certain)s THEN 'certain' WHEN score >= %(strong)s THEN 'strong'
                       ELSE 'weak' END AS band
           FROM {against}) l USING (a_user_id, b_user_id)
GROUP BY 1, 2
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
        found = band in RECALLED_BANDS
        bands[band] += 1
        if top_signal:
            signal_linked[top_signal] += 1
            signal_found[top_signal] += found
        for name in shared:
            evidence_pairs[name] += 1
            evidence_found[name] += found
    return {"pairs": len(items), "found": sum(bands[band] for band in RECALLED_BANDS), "bands": bands,
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


def links_source(links_name=LINKS, variant=None):
    if variant is None:
        return links_table(links_name)
    if not VARIANT_NAME.match(variant) or variant == LIVE_VARIANT:
        raise ValueError(f"{variant!r} is not a variant name")
    return sql.SQL("(SELECT * FROM {} WHERE variant = {})").format(
        links_table(SHADOW_LINKS), sql.Literal(variant))


def draw_samples(conn, per_band, bands=SAMPLE_BANDS, variant=None):
    thresholds = scoring()
    text = sql.SQL(DRAW_SQL).format(links=links_source(LINKS, variant))
    rows = conn.execute(text, {"certain": thresholds["certain"], "strong": thresholds["strong"],
                               "variant": variant or LIVE_VARIANT, "bands": list(bands),
                               "per_band": per_band}).fetchall()
    conn.commit()
    return Counter(band for (band,) in rows)


def sample_precision(rows, targets):
    precision_targets = (targets or {}).get("precision", {})
    counts = {band: (drawn, right, wrong) for band, drawn, right, wrong in rows}
    return {band: {"drawn": counts[band][0], "right": counts[band][1], "wrong": counts[band][2],
                   "target": precision_targets.get(SAMPLE_TARGET_KEYS[band])}
            for band in SAMPLE_BANDS if band in counts}


def band_shift(rows):
    shift = {"added": Counter(), "dropped": Counter(), "up": 0, "down": 0, "same": 0}
    for variant_band, live_band, count in rows:
        if live_band is None:
            shift["added"][BAND_DISPLAY[variant_band]] += count
        elif variant_band is None:
            shift["dropped"][BAND_DISPLAY[live_band]] += count
        elif BAND_ORDER[variant_band] > BAND_ORDER[live_band]:
            shift["up"] += count
        elif BAND_ORDER[variant_band] < BAND_ORDER[live_band]:
            shift["down"] += count
        else:
            shift["same"] += count
    return shift


def measure(conn, links_name=LINKS, variant=None, against=None):
    thresholds = scoring()
    config = catalogue()
    staff = config.get("staff_domains", [])
    targets = config.get("band_targets")
    links = links_source(links_name, variant)

    def query(text, params=None, **parts):
        return conn.execute(sql.SQL(text).format(links=links, **parts), params).fetchall()

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

    post_ban = query(POST_BAN_SQL, {"bot_user_ids": list(BOT_USER_IDS), "reban_window_days": REBAN_WINDOW_DAYS,
                                    "home_ip_max_users": HOME_IP_MAX_USERS,
                                    "vpn_ip_max_users": VPN_IP_MAX_USERS})
    same_person = [(score, top_signal, ()) for _a, _b, verdict, score, top_signal in rows
                   if verdict == "same_person"]
    samples = None
    sample_variant = variant or (LIVE_VARIANT if links_name == LINKS else None)
    if sample_variant:
        sample_rows = conn.execute(SAMPLE_PRECISION_SQL, {"right": list(RIGHT), "wrong": list(WRONG),
                                                          "variant": sample_variant}).fetchall()
        samples = sample_precision(sample_rows, targets)
    shift = None
    if variant:
        shift = band_shift(query(BAND_SHIFT_SQL, thresholds, against=links_source(LINKS, against)))

    return {
        "links": f"{SHADOW_LINKS} ({variant})" if variant else links_name,
        "variant": variant,
        "against": f"{SHADOW_LINKS} ({against})" if against else LINKS,
        "shift": shift,
        "bands": dict(zip(BAND_NAMES, banded, strict=True)),
        "recall": {
            "post-ban": recall([(score, top_signal, evidence)
                                for _a, _b, score, top_signal, evidence in post_ban], thresholds),
            "same person": recall(same_person, thresholds),
        },
        "samples": samples,
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


def format_ratios(counts):
    ordered = sorted(counts.items(), key=lambda item: (-item[1][1], item[0]))
    return ", ".join(f"{name} {found:,} of {total:,}" for name, (found, total) in ordered)


def recall_lines(recalls, baseline=None, baseline_name="live"):
    lines = [f"recall at strong or above (post-ban: banned again within {REBAN_WINDOW_DAYS} days, "
             f"sharing an inbox, a home address held by {HOME_IP_MAX_USERS} or fewer, "
             f"or a VPN exit held by {VPN_IP_MAX_USERS} or fewer on one build)"]
    for name, one in recalls.items():
        live = (baseline or {}).get(name)
        live_text = f"  ({baseline_name} {live['found']:,} of {live['pairs']:,})" if live else ""
        lines.append(f"  {name:<17} {one['found']:>6,} of {one['pairs']:<6,} "
                     f"{share(one['found'], one['pairs']):>4}  {band_line(one['bands'])}, "
                     f"{UNLINKED} {one['bands'].get(UNLINKED, 0):,}{live_text}")
        if one["evidence"]:
            lines.append(f"    by what they share  {format_ratios(one['evidence'])}")
        if one["signals"]:
            lines.append(f"    by top signal       {format_ratios(one['signals'])}")
    lines.append("")
    return lines


def sample_lines(samples, variant=None):
    if not samples:
        draw = f"check-links --draw 50 --variant {variant}" if variant else "check-links --draw 50"
        return [f"sampled links: none drawn yet ({draw})", ""]
    lines = ["sampled links, labelled on Compare (Links > Sampled)"]
    for band, one in samples.items():
        labelled_count = one["right"] + one["wrong"]
        target = f", target {share(one['target'], 1)}" if one["target"] is not None else ""
        lines.append(f"  {band:<8} {labelled_count:>4,} labelled of {one['drawn']:<4,} "
                     f"precision {share(one['right'], labelled_count)}{target}")
    lines.append("")
    return lines


def shift_lines(shift, against=LINKS):
    added = sum(shift["added"].values())
    dropped = sum(shift["dropped"].values())
    return [f"against {against}: {added:,} added ({band_line(shift['added'])}), "
            f"{dropped:,} dropped ({band_line(shift['dropped'])}), "
            f"{shift['up']:,} moved up a band, {shift['down']:,} moved down, {shift['same']:,} unchanged", ""]


def render(result):
    bands = result["bands"]
    lines = [f"links in {result['links']}: {sum(bands.values()):,} ({band_line(bands)})", ""]

    if result.get("shift"):
        lines.extend(shift_lines(result["shift"], result.get("against", LINKS)))
    if result.get("recall"):
        lines.extend(recall_lines(result["recall"], result.get("baseline"), result.get("baseline_name", "live")))
    if result.get("samples") is not None:
        lines.extend(sample_lines(result["samples"], result.get("variant")))

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
                 f"{cutoffs['wrong']:,} different people")
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
    parser.add_argument("--variant", metavar="NAME",
                        help="score the links nemo links --variant built under NAME in fd.member_link_shadow")
    parser.add_argument("--against", metavar="NAME",
                        help="compare the --variant with another variant instead of fd.member_link, "
                             "such as one built from an empty file")
    parser.add_argument("--draw", type=int, metavar="N",
                        help="add N links per band to fd.link_sample, spread across top signals; "
                             "from fd.member_link, or from the --variant set")
    parser.add_argument("--band", choices=SAMPLE_BANDS, action="append",
                        help="draw only from this band; repeat for more than one")
    args = parser.parse_args(argv)
    load_dotenv(ENV_FILE)
    try:
        links_source(args.links, args.variant)
        links_source(LINKS, args.against)
    except ValueError as error:
        print(f"check-links: {error}", file=sys.stderr)
        return 2
    if args.variant and args.links != LINKS:
        print("check-links: --variant reads fd.member_link_shadow, so it takes no --links", file=sys.stderr)
        return 2
    if args.against and not args.variant:
        print("check-links: --against compares a --variant, so it needs one", file=sys.stderr)
        return 2
    if args.draw is not None and (args.draw < 1 or args.links != LINKS):
        print(f"check-links: --draw takes a positive count and samples {LINKS} or a --variant", file=sys.stderr)
        return 2
    try:
        with connect(args.dsn) as conn:
            if args.draw is not None:
                drawn = draw_samples(conn, args.draw, args.band or SAMPLE_BANDS, args.variant)
                print("check-links: drew " + ", ".join(f"{drawn.get(band, 0):,} {band}" for band in SAMPLE_BANDS)
                      + f" into fd.link_sample as {args.variant or LIVE_VARIANT}")
                return 0
            conn.read_only = True
            result = measure(conn, args.links, args.variant, args.against)
            if args.variant:
                result["baseline"] = measure(conn, variant=args.against)["recall"]
                result["baseline_name"] = args.against or "live"
    except (errors.UndefinedTable, errors.UndefinedColumn) as error:
        print(f"check-links: {str(error).splitlines()[0]}", file=sys.stderr)
        return 2
    print("\n".join(render(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
