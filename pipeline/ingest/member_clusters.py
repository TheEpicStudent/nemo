from datetime import timedelta

from ingest import member_links as links
from lib.db import ingest_run
from lib.graph import components

SOURCE = "member_clusters"
TOGETHER = ("same_person", "allowed_alt")
APART = ("different_people",)
SIGNAL_FAMILIES = (links.NETWORK, links.DEVICE, links.IDENTITY, links.NAME, links.ARRIVAL)
STRONG_EDGE_FAMILIES = 2

EDGES_SQL = """
SELECT l.a_user_id, l.b_user_id
FROM fd.member_link l
WHERE (l.score >= %(certain)s
       OR (l.score >= %(edge)s
           AND (SELECT count(*) FROM jsonb_each_text(l.families) f
                WHERE f.key = ANY(%(families)s) AND f.value::numeric > 0) >= %(strong_families)s))
  AND NOT EXISTS (SELECT 1 FROM fd.member_link_verdict v
                  WHERE v.a_user_id = l.a_user_id AND v.b_user_id = l.b_user_id
                    AND v.verdict = ANY(%(apart)s))
UNION
SELECT a_user_id, b_user_id FROM fd.member_link_verdict WHERE verdict = ANY(%(together)s)
"""

APART_SQL = "SELECT a_user_id, b_user_id FROM fd.member_link_verdict WHERE verdict = ANY(%s)"

ACCOUNTS_SQL = """
SELECT m.user_id, NOT m.is_deleted, j.joined_at
FROM fd.member m
LEFT JOIN fd.member_joins j ON j.user_id = m.user_id
WHERE m.user_id = ANY(%s)
"""

UPSERT_SQL = """
INSERT INTO fd.member_cluster (user_id, cluster_id, accounts, ring, active, conflict, computed_at)
VALUES (%s, %s, %s, %s, %s, %s, now())
ON CONFLICT (user_id) DO UPDATE SET
    cluster_id = EXCLUDED.cluster_id,
    accounts = EXCLUDED.accounts,
    ring = EXCLUDED.ring,
    active = EXCLUDED.active,
    conflict = EXCLUDED.conflict,
    computed_at = EXCLUDED.computed_at
WHERE (fd.member_cluster.cluster_id, fd.member_cluster.accounts, fd.member_cluster.ring,
       fd.member_cluster.active, fd.member_cluster.conflict)
      IS DISTINCT FROM (EXCLUDED.cluster_id, EXCLUDED.accounts, EXCLUDED.ring, EXCLUDED.active,
                        EXCLUDED.conflict)
"""

SWEEP = "DELETE FROM fd.member_cluster WHERE NOT (user_id = ANY(%s))"


def settings(catalogue=None):
    return (catalogue or links.catalogue())["clusters"]


def burst(times, window):
    ordered = sorted(one for one in times if one is not None)
    peak = 0
    start = 0
    for end, at in enumerate(ordered):
        while at - ordered[start] > window:
            start += 1
        peak = max(peak, end - start + 1)
    return peak


def oldest(group, joined):
    return min(group, key=lambda one: (joined.get(one) is None, joined.get(one) or 0, one))


def conflicted(group, apart):
    return any(a in group and b in group for a, b in apart)


def cluster_rows(groups, accounts, rule, apart=()):
    joined = {user_id: at for user_id, (_active, at) in accounts.items()}
    window = timedelta(minutes=rule["window_minutes"])
    rows = []
    for group in groups:
        cluster_id = oldest(group, joined)
        is_burst = (len(group) >= rule["min_accounts"]
                    and burst([joined.get(one) for one in group], window) >= rule["min_accounts"])
        conflict = conflicted(group, apart)
        for user_id in sorted(group):
            active = accounts.get(user_id, (True, None))[0]
            rows.append((user_id, cluster_id, len(group), is_burst, active, conflict))
    return rows


def run(conn):
    config = settings()
    with ingest_run(conn, SOURCE) as counts:
        edges = conn.execute(EDGES_SQL, {"edge": config["edge_score"], "certain": links.scoring()["certain"],
                                         "families": list(SIGNAL_FAMILIES),
                                         "strong_families": STRONG_EDGE_FAMILIES,
                                         "apart": list(APART), "together": list(TOGETHER)}).fetchall()
        apart = [(a, b) for a, b in conn.execute(APART_SQL, (list(APART),)).fetchall()]
        groups = components((a, b) for a, b in edges)
        members = sorted(set().union(*groups)) if groups else []
        accounts = {row[0]: (row[1], row[2])
                    for row in conn.execute(ACCOUNTS_SQL, (members,)).fetchall()} if members else {}
        rows = cluster_rows(groups, accounts, config["ring"], apart)
        with conn.cursor() as cur:
            if rows:
                cur.executemany(UPSERT_SQL, rows)
            cur.execute(SWEEP, (members,))
            removed = cur.rowcount
        conn.commit()
        counts.rows_in = len(rows)

    burst_count = len({row[1] for row in rows if row[3]})
    conflicts = len({row[1] for row in rows if row[5]})
    print(f"{SOURCE}: {len(groups)} cluster(s) over {len(rows)} account(s), {burst_count} ring(s), "
          f"{conflicts} holding accounts FD marked as different people, "
          f"{removed} account(s) no longer clustered")
    return len(rows)
