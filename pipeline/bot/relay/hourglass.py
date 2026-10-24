import logging

from slack_sdk.errors import SlackApiError

from bot.core import session

log = logging.getLogger("bot.relay")

HOURGLASS = "hourglass"
BATCH = 50
SETTLED = ("no_reaction", "message_not_found", "channel_not_found", "not_in_channel", "is_archived",
           "thread_not_found")

WAITING = """
WITH RECURSIVE chain AS (
    SELECT r.id AS report_id, c.id AS case_id, c.duplicate_of, c.resolved_at, 0 AS hops
    FROM fd.case_reports r
    JOIN fd.cases c ON c.id = r.case_id
    WHERE r.source_app = 'shroud' AND r.hourglass_removed_at IS NULL
      AND r.forwarded_ts IS NOT NULL AND r.card_channel_id IS NOT NULL
    UNION ALL
    SELECT chain.report_id, c.id, c.duplicate_of, c.resolved_at, chain.hops + 1
    FROM chain
    JOIN fd.cases c ON c.id = chain.duplicate_of
    WHERE chain.hops < 10
)
SELECT r.id, r.card_channel_id, r.forwarded_ts
FROM fd.case_reports r
WHERE r.id IN (
    SELECT report_id FROM chain
    GROUP BY report_id
    HAVING bool_or(resolved_at > (SELECT ok_at FROM fd.lyla_sync_status WHERE name = 'import'))
       AND (%(case_id)s::bigint IS NULL OR bool_or(case_id = %(case_id)s))
)
ORDER BY r.id
LIMIT %(limit)s
"""

REMOVED = "UPDATE fd.case_reports SET hourglass_removed_at = now() WHERE id = %s"


def waiting(conn, case_id=None, limit=BATCH):
    return conn.execute(WAITING, {"case_id": case_id, "limit": limit}).fetchall()


def release(client, case_id=None, limit=BATCH):
    with session() as conn:
        rows = waiting(conn, case_id, limit)
    released = 0
    for report_id, channel_id, forwarded_ts in rows:
        try:
            client.reactions_remove(channel=channel_id, timestamp=forwarded_ts, name=HOURGLASS)
        except SlackApiError as failure:
            error = (failure.response or {}).get("error", "")
            if error not in SETTLED:
                log.warning("relay: report %s keeps Shroud's hourglass for now: %s", report_id, error)
                continue
        with session() as conn:
            conn.execute(REMOVED, (report_id,))
        released += 1
    if released:
        log.info("relay: took Shroud's hourglass off %s resolved report(s)", released)
    return released
