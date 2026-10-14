import logging

from bot.core import session
from bot.nemo import guard_actions

log = logging.getLogger("bot.nemo")

MOST = 100
CEILING = 500
PAGE = 200
MAX_PASSES = 12

WAITING = """
SELECT id, channel_id, wanted, asked_by
FROM fd.purges
WHERE state = 'asked' AND channel_id IS NOT NULL AND member_id IS NULL
ORDER BY asked_at
LIMIT 20
"""

CLAIM = """
UPDATE fd.purges
SET state = 'running', started_at = now()
WHERE id = %s AND state = 'asked' AND channel_id IS NOT NULL AND member_id IS NULL
RETURNING channel_id, wanted
"""

DONE = """
UPDATE fd.purges
SET state = 'done', finished_at = now(), taken_down = %s
WHERE id = %s AND state = 'running'
"""

FAILED = """
UPDATE fd.purges
SET state = 'failed', finished_at = now(), taken_down = %s, error = %s
WHERE id = %s AND state = 'running'
"""

ITEMS = """
INSERT INTO fd.purge_items (purge_id, channel_id, ts, thread_ts, author_id, text, state, done_at)
SELECT %s, %s, taken.ts, taken.thread_ts, taken.author_id, taken.text, 'deleted', now()
FROM unnest(%s::text[], %s::text[], %s::text[], %s::text[])
    AS taken(ts, thread_ts, author_id, text)
ON CONFLICT (purge_id, channel_id, ts) DO NOTHING
"""


class PurgeLimitExceeded(RuntimeError):
    """Raised when a thread exceeds the maximum messages a purge may delete."""


def waiting(conn):
    return conn.execute(WAITING).fetchall()


def claim(conn, purge_id):
    return conn.execute(CLAIM, (purge_id,)).fetchone()


def deletable(message):
    return message.get("subtype") != "channel_join" and message.get("ts")


def has_replies(message):
    if message.get("reply_count"):
        return True
    return bool(message.get("thread_ts")) and message.get("thread_ts") == message.get("ts")


def newest(client, channel_id, max_messages):
    messages = []
    cursor = None
    while len(messages) < max_messages:
        params = {"channel": channel_id, "limit": min(PAGE, max_messages - len(messages))}
        if cursor:
            params["cursor"] = cursor
        response = client.conversations_history(**params) or {}
        for message in response.get("messages") or []:
            if not deletable(message):
                continue
            messages.append(message)
            if len(messages) >= max_messages:
                break
        cursor = ((response.get("response_metadata") or {}).get("next_cursor") or "").strip()
        if not cursor:
            break
    return messages


def replies(client, channel_id, thread_ts):
    messages, cursor = [], None
    while True:
        response = client.conversations_replies(
            channel=channel_id, ts=thread_ts, limit=PAGE, cursor=cursor
        ) or {}
        for message in response.get("messages") or []:
            if message.get("ts") and message["ts"] != thread_ts:
                messages.append(message)
        cursor = ((response.get("response_metadata") or {}).get("next_cursor") or "").strip()
        if not cursor:
            return messages


def transcript_entry(message, thread_ts=None):
    return {
        "ts": message.get("ts"),
        "thread_ts": thread_ts,
        "user": message.get("user") or message.get("bot_id"),
        "text": message.get("text"),
    }


def keep(conn, purge_id, channel_id, deleted):
    if not deleted:
        return
    conn.execute(ITEMS, (
        purge_id, channel_id,
        [entry["ts"] for entry in deleted],
        [entry["thread_ts"] for entry in deleted],
        [entry["user"] for entry in deleted],
        [entry["text"] for entry in deleted],
    ))


def delete_thread_replies(client, channel_id, parent, deleted):
    thread_ts = parent["ts"]
    for _ in range(MAX_PASSES):
        thread_replies = replies(client, channel_id, thread_ts)
        if not thread_replies:
            break
        for message in thread_replies:
            if len(deleted) >= CEILING:
                raise PurgeLimitExceeded(f"more than {CEILING} messages hang off {channel_id}")
            guard_actions.remove(client, channel_id, message["ts"])
            deleted.append(transcript_entry(message, thread_ts))


def delete_messages(client, channel_id, message, deleted):
    if has_replies(message):
        delete_thread_replies(client, channel_id, message, deleted)
    if len(deleted) >= CEILING:
        raise PurgeLimitExceeded(f"more than {CEILING} messages hang off {channel_id}")
    guard_actions.remove(client, channel_id, message["ts"])
    deleted.append(transcript_entry(message))


def run(client, purge_id):
    with session() as conn:
        claimed = claim(conn, purge_id)
    if claimed is None:
        return 0

    channel_id, requested_count = claimed
    deleted = []
    failure = None
    try:
        for message in newest(client, channel_id, min(requested_count, MOST)):
            delete_messages(client, channel_id, message, deleted)
    except Exception as error:
        failure = str(error)[:500]
        log.warning("nemo: purge %s stopped after %s: %s", purge_id, len(deleted), failure)

    with session() as conn:
        keep(conn, purge_id, channel_id, deleted)
        conn.execute(FAILED if failure else DONE,
                     (len(deleted), failure, purge_id) if failure else (len(deleted), purge_id))

    log.info("nemo: purge %s took down %s in %s", purge_id, len(deleted), channel_id)
    return len(deleted)
