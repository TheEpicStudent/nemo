import logging

from bot.core import session
from bot.nemo import channels

log = logging.getLogger("bot.nemo")

JOINED = "joined"
REFUSED = "refused"

CLAIM = """
SELECT channel_id, requested_by FROM fd.channel_join_requests
WHERE id = %s AND state = 'queued'
FOR UPDATE SKIP LOCKED
"""

FINISH = """
UPDATE fd.channel_join_requests SET state = %s, error = %s, finished_at = now()
WHERE id = %s
"""

QUEUED = """
SELECT id FROM fd.channel_join_requests WHERE state = 'queued'
ORDER BY requested_at LIMIT 20
"""

LAST_REFUSAL = """
SELECT why FROM fd.channel_joins
WHERE channel_id = %s AND verb = 'refused'
ORDER BY at DESC, id DESC LIMIT 1
"""


def queued(conn):
    return [row[0] for row in conn.execute(QUEUED).fetchall()]


def refusal_reason(conn, channel_id):
    row = conn.execute(LAST_REFUSAL, (channel_id,)).fetchone()
    return (row and row[0]) or REFUSED


def run(client, request_id):
    with session() as conn:
        row = conn.execute(CLAIM, (request_id,)).fetchone()
        if row is None:
            return None
        channel_id, requested_by = row

        if not channels.joinable(conn, channel_id):
            channels.record_join_event(conn, channel_id, REFUSED, channels.NEEDS_INVITE, requested_by)
            state, error = REFUSED, channels.NEEDS_INVITE
        elif channels.join(client, conn, channel_id, by=requested_by):
            state, error = JOINED, None
        else:
            state, error = REFUSED, refusal_reason(conn, channel_id)
        conn.execute(FINISH, (state, error, request_id))

    log.info("nemo: join request %s for %s by %s ended %s%s", request_id, channel_id,
             requested_by, state, f" ({error})" if error else "")
    return state
