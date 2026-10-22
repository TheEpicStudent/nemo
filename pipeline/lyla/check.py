from lyla import mapping

LYLA_STATUSES = "SELECT status, count(*) FROM cases WHERE case_number <> ALL(%s) GROUP BY status"

LYLA_NUMBERS = "SELECT case_number FROM cases"

NEMO_STATUSES = """
SELECT CASE WHEN resolved_at IS NULL THEN 'open'
            WHEN resolution = 'not_conduct' THEN 'canceled'
            WHEN resolution = 'duplicate' THEN 'merged'
            ELSE 'resolved' END, count(*)
FROM fd.cases WHERE id = ANY(%s)
GROUP BY 1
"""

NEMO_IDS = "SELECT id FROM fd.cases"

ALIASES = """
SELECT source_key::bigint FROM fd.import_map
WHERE source_app = 'lyla' AND source_table = 'cases' AND entity_id::text <> source_key
"""

FALLBACK = "SELECT count(*) FROM fd.cases WHERE id >= %s"

OUTBOX = """
SELECT count(*) FILTER (WHERE applied_at IS NULL),
       count(*) FILTER (WHERE applied_at IS NULL AND error IS NOT NULL),
       count(*) FILTER (WHERE conflict IS NOT NULL AND queued_at > now() - interval '1 day'),
       min(queued_at) FILTER (WHERE applied_at IS NULL)
FROM fd.lyla_outbox
"""

SYNC = "SELECT name, ran_at, ok_at, error FROM fd.lyla_sync_status ORDER BY name"

UCAT = """
SELECT count(*) FROM case_actions
WHERE case_number <> 0 AND (ucat_id IS NULL OR ucat_sync_pending)
  AND coalesce(updated_at, performed_at) < %s
"""

FALLBACK_START = 100000
UCAT_GRACE_MS = 30 * 60 * 1000


def report(conn, lyla):
    lyla_numbers = {row[0] for row in lyla.execute(LYLA_NUMBERS).fetchall()}
    nemo_ids = {row[0] for row in conn.execute(NEMO_IDS).fetchall()}
    aliases = {row[0] for row in conn.execute(ALIASES).fetchall()}
    left_out = sorted(mapping.SKIPPED_CASES | aliases)
    kept = sorted(lyla_numbers - set(left_out))
    lyla_counts = dict(lyla.execute(LYLA_STATUSES, (left_out,)).fetchall())
    nemo_counts = dict(conn.execute(NEMO_STATUSES, (kept,)).fetchall())
    lines = []
    for name in (mapping.OPEN, mapping.RESOLVED, mapping.CANCELED, mapping.MERGED, mapping.EXPIRED):
        lines.append(f"cases {name}: LYLA {lyla_counts.get(name, 0)}, Nemo {nemo_counts.get(name, 0)}")
    missing = sorted(set(kept) - nemo_ids)
    extra = sorted(one for one in nemo_ids - lyla_numbers if one < FALLBACK_START)
    lines.append(f"cases only in LYLA: {len(missing)} {missing[:20]}")
    lines.append(f"LYLA cases merged into a Nemo case: {len(aliases)} {sorted(aliases)[:20]}")
    lines.append(f"cases only in Nemo: {len(extra)} {extra[:20]}")
    lines.append(f"cases in the fallback range: {conn.execute(FALLBACK, (FALLBACK_START,)).fetchone()[0]}")
    waiting, errors, conflicts, oldest = conn.execute(OUTBOX).fetchone()
    lines.append(f"outbox waiting: {waiting}, errors: {errors}, conflicts in the last day: {conflicts}, "
                 f"oldest waiting: {oldest or '-'}")
    for name, ran_at, ok_at, error in conn.execute(SYNC).fetchall():
        lines.append(f"{name}: ran {ran_at}, ok {ok_at}" + (f", error {error}" if error else ""))
    cutoff = mapping.to_ms(conn.execute("SELECT now()").fetchone()[0]) - UCAT_GRACE_MS
    lines.append(f"UCAT waiting over 30 minutes: {lyla.execute(UCAT, (cutoff,)).fetchone()[0]}")
    lyla.commit()
    return lines
