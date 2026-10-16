from psycopg.types.json import Jsonb

GIVE_UP_AFTER = 3

STALE_CLAIM = "5 minutes"

CLAIM = """
UPDATE fd.intake_outbox SET claimed_at = now()
WHERE id IN (
    SELECT id FROM fd.intake_outbox
    WHERE sent_at IS NULL AND failed_at IS NULL
      AND (claimed_at IS NULL OR claimed_at < now() - interval '%(stale)s')
      %(mine)s
    ORDER BY requested_at
    LIMIT 20
    FOR UPDATE SKIP LOCKED
)
RETURNING id
"""

CLAIMED = """
SELECT o.id, o.conversation_id, o.kind, o.body, o.mode, o.requested_by, o.attempts,
       c.channel_id, c.thread_ts, c.closed_at, o.files, o.edits_outbox_id
FROM fd.intake_outbox o
JOIN fd.intake_conversations c ON c.id = o.conversation_id
WHERE o.id = ANY(%s)
ORDER BY o.requested_at
"""

QUEUE = """
INSERT INTO fd.intake_outbox
    (conversation_id, kind, body, mode, requested_by, files, asked_in_channel, asked_at_ts,
     edits_outbox_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""

REPLY_AT = """
SELECT o.id, o.conversation_id, o.mode, o.sent_at,
       coalesce((SELECT e.body FROM fd.intake_outbox e WHERE e.edits_outbox_id = o.id
                 ORDER BY e.id DESC LIMIT 1), o.body)
FROM fd.intake_outbox o
WHERE o.asked_in_channel = %s AND o.asked_at_ts = %s AND o.kind = 'reply'
ORDER BY o.id LIMIT 1
"""

EDIT_UNSENT = """
UPDATE fd.intake_outbox SET body = %s
WHERE id = %s AND sent_at IS NULL AND failed_at IS NULL AND claimed_at IS NULL
RETURNING id
"""

TO_ECHO = """
SELECT o.id, o.body, o.mode, o.requested_by, r.forwarded_ts, r.card_channel_id
FROM fd.intake_outbox o
JOIN fd.intake_conversations c ON c.id = o.conversation_id
JOIN fd.case_reports r ON r.id = c.report_id
WHERE o.echoed_at IS NULL AND r.forwarded_ts IS NOT NULL
  AND (NOT EXISTS (SELECT 1 FROM fd.staff_slack s
                    WHERE s.staff_user_id = o.requested_by AND s.revoked_at IS NULL)
       OR coalesce(o.sent_at, o.failed_at) < now() - interval '2 minutes')
"""

TO_TICK = """
SELECT o.id, coalesce(o.asked_in_channel, r.card_channel_id), coalesce(o.asked_at_ts, o.echoed_ts),
       o.failed_at, o.error
FROM fd.intake_outbox o
LEFT JOIN fd.intake_conversations c ON c.id = o.conversation_id
LEFT JOIN fd.case_reports r ON r.id = c.report_id
WHERE o.ticked_at IS NULL
  AND coalesce(o.asked_at_ts, o.echoed_ts) IS NOT NULL
  AND (o.sent_at IS NOT NULL OR o.failed_at IS NOT NULL)
"""

ON_CASE = """
 AND c.report_id IN (SELECT id FROM fd.case_reports WHERE case_id = %s)
"""

ECHO_ORDER = " ORDER BY o.requested_at LIMIT 50"


def claim_sql(conversation_id=None):
    mine = "AND conversation_id = %s" if conversation_id is not None else ""
    return CLAIM % {"stale": STALE_CLAIM, "mine": mine}

ANY_WAITING = """
SELECT DISTINCT conversation_id FROM fd.intake_outbox
WHERE sent_at IS NULL AND failed_at IS NULL
LIMIT 50
"""

SENT = """
UPDATE fd.intake_outbox SET sent_at = now(), message_id = %s, attempts = attempts + 1
WHERE id = %s AND sent_at IS NULL
"""

TRIED = """
UPDATE fd.intake_outbox SET attempts = attempts + 1 WHERE id = %s
"""

CLAIM_ECHO = """
UPDATE fd.intake_outbox SET echoed_at = now()
WHERE id = %s AND echoed_at IS NULL
RETURNING id
"""

ECHOED = """
UPDATE fd.intake_outbox SET echoed_ts = %s, echoed_as = %s WHERE id = %s
"""

DROP_ECHO = """
UPDATE fd.intake_outbox SET echoed_at = NULL WHERE id = %s AND echoed_ts IS NULL
"""

TICK_ORDER = " ORDER BY o.requested_at LIMIT 50"

TICKED = """
UPDATE fd.intake_outbox SET ticked_at = now() WHERE id = %s
"""

GAVE_UP = """
UPDATE fd.intake_outbox
SET attempts = attempts + 1, failed_at = now(), error = %s
WHERE id = %s AND sent_at IS NULL
"""


class QueuedMessage:
    def __init__(self, row):
        (
            self.id,
            self.conversation_id,
            self.kind,
            self.body,
            self.mode,
            self.requested_by,
            self.attempts,
            self.channel_id,
            self.thread_ts,
            self.closed_at,
            self.files,
            self.edits_outbox_id,
        ) = row

    @property
    def last_try(self):
        return self.attempts + 1 >= GIVE_UP_AFTER


def waiting(conn, conversation_id=None):
    sql = claim_sql(conversation_id)
    if conversation_id is None:
        claimed = conn.execute(sql).fetchall()
    else:
        claimed = conn.execute(sql, (conversation_id,)).fetchall()
    if not claimed:
        return []

    rows = conn.execute(CLAIMED, ([one[0] for one in claimed],)).fetchall()
    return [QueuedMessage(row) for row in rows]


def any_waiting(conn):
    return [row[0] for row in conn.execute(ANY_WAITING).fetchall()]


def queue(conn, conversation_id, kind, body, requested_by, mode="signed",
          files=None, requested_in=None, requested_at=None, edits_outbox_id=None):
    return conn.execute(
        QUEUE,
        (conversation_id, kind, body, mode, requested_by,
         Jsonb(files or []), requested_in, requested_at, edits_outbox_id),
    ).fetchone()[0]


def reply_at(conn, channel_id, ts):
    return conn.execute(REPLY_AT, (channel_id, ts)).fetchone()


def edit_reply(conn, channel_id, ts, body, edited_by):
    row = reply_at(conn, channel_id, ts)
    if row is None:
        return None
    outbox_id, conversation_id, mode, sent_at, current_body = row
    if body == current_body:
        return None
    if sent_at is None and conn.execute(EDIT_UNSENT, (body, outbox_id)).fetchone():
        return outbox_id
    edit_id = queue(conn, conversation_id, "edit", body, edited_by, mode=mode,
                    requested_in=channel_id, requested_at=ts, edits_outbox_id=outbox_id)
    claim_echo(conn, edit_id)
    echoed(conn, edit_id, None, "user")
    return edit_id


def to_echo(conn, case_id=None):
    sql = TO_ECHO + (ON_CASE if case_id is not None else "") + ECHO_ORDER
    return conn.execute(sql, (case_id,) if case_id is not None else ()).fetchall()


def to_tick(conn):
    return conn.execute(TO_TICK + TICK_ORDER).fetchall()


def sent(conn, outbox_id, message_id):
    conn.execute(SENT, (message_id, outbox_id))


def ticked(conn, outbox_id):
    conn.execute(TICKED, (outbox_id,))


def claim_echo(conn, outbox_id):
    return conn.execute(CLAIM_ECHO, (outbox_id,)).fetchone() is not None


def echoed(conn, outbox_id, ts, how):
    conn.execute(ECHOED, (ts, how, outbox_id))


def drop_echo(conn, outbox_id):
    conn.execute(DROP_ECHO, (outbox_id,))


def mark_error(conn, outbox_id, error, give_up):
    if give_up:
        conn.execute(GAVE_UP, (str(error)[:500], outbox_id))
    else:
        conn.execute(TRIED, (outbox_id,))
