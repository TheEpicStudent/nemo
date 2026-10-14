from datetime import datetime, timezone

from lib import member_seen
from lib.message import author_kind, redact, normalize

DELETED_SUBTYPE = "message_deleted"
CHANGED = "message_changed"
WRAPPERS = frozenset({DELETED_SUBTYPE, CHANGED})
FETCHED = 1
EVENT = "event"

FIELDS = (
    "channel_id", "ts", "revision", "posted_at", "author_id", "author_kind", "bot_id",
    "app_id", "parent_user_id", "subtype", "thread_root_ts", "is_reply", "is_broadcast",
    "reply_count", "reply_users_count", "latest_reply_ts", "text_length", "has_text",
    "block_count", "attachment_count", "file_count", "mention_count", "mentioned_ids",
    "is_question", "is_substantive", "has_link", "emoji_only", "reaction_count",
    "reactor_count", "edited_at", "edited_by", "client_msg_id", "team_id",
)

COALESCED_FIELDS = (
    "author_id", "bot_id", "app_id", "parent_user_id", "subtype", "text_length", "has_text",
    "block_count", "attachment_count", "file_count", "mention_count", "mentioned_ids",
    "is_question", "is_substantive", "has_link", "emoji_only", "reaction_count",
    "reactor_count", "edited_at", "edited_by", "client_msg_id", "team_id",
)

ALWAYS = ("revision", "posted_at", "author_kind", "is_reply", "is_broadcast",
          "thread_root_ts", "reply_count", "reply_users_count", "latest_reply_ts")

AUTHOR, KIND, SUBTYPE, POSTED = (
    FIELDS.index(name) for name in ("author_id", "author_kind", "subtype", "posted_at")
)


def member_posts(rows):
    return [(row[AUTHOR], row[POSTED]) for row in rows
            if row[KIND] == "member" and row[AUTHOR] and row[SUBTYPE] != "channel_join"]


COLUMNS = (*FIELDS, "settled")


def _merged(new, old):
    merged = {name: new(name) for name in ALWAYS}
    merged.update({name: f"coalesce({new(name)}, {old}.{name})" for name in COALESCED_FIELDS})
    merged["settled"] = f"{old}.settled OR {new('settled')}"
    return merged


def _changes(new, old):
    merged = _merged(new, old)
    before = ", ".join(f"{old}.{name}" for name in merged)
    after = ", ".join(f"({value})" for value in merged.values())
    return f"(NOT {old}.settled OR {new('settled')}) AND ({before}) IS DISTINCT FROM ({after})"


def _upsert():
    excluded = "EXCLUDED.{}".format
    placeholder = "%({})s".format
    sets = ", ".join([f"{name} = {value}"
                      for name, value in _merged(excluded, "archive.message").items()]
                     + ["updated_at = now()"])
    return (
        f"INSERT INTO archive.message ({', '.join(COLUMNS)}) "
        f"SELECT {', '.join(placeholder(name) for name in COLUMNS)} "
        f"WHERE NOT EXISTS (SELECT 1 FROM archive.message held "
        f"WHERE held.channel_id = %(channel_id)s AND held.ts = %(ts)s "
        f"AND ({_changes(placeholder, 'held')}) IS NOT TRUE) "
        f"ON CONFLICT (channel_id, ts) DO UPDATE SET {sets} "
        f"WHERE {_changes(excluded, 'archive.message')}"
    )


MESSAGE_SQL = _upsert()

EDIT_MEASURES = (
    "text_length", "has_text", "block_count", "attachment_count", "mention_count",
    "mentioned_ids", "is_question", "is_substantive", "has_link", "emoji_only",
)
EDIT_KEPT_UNLESS_SENT = ("file_count", "edited_at", "edited_by")


def _edit():
    sent = [f"%({name})s" for name in EDIT_MEASURES]
    sent += [f"coalesce(%({name})s, {name})" for name in EDIT_KEPT_UNLESS_SENT]
    columns = (*EDIT_MEASURES, *EDIT_KEPT_UNLESS_SENT)
    sets = ", ".join(f"{name} = {value}" for name, value in zip(columns, sent))
    return (
        f"UPDATE archive.message SET {sets}, updated_at = now() "
        f"WHERE channel_id = %(channel_id)s AND ts = %(ts)s "
        f"AND ({', '.join(columns)}) IS DISTINCT FROM ({', '.join(sent)})"
    )


EDIT_SQL = _edit()

HELD_SQL = "SELECT 1 FROM archive.message WHERE channel_id = %s AND ts = %s"

DELETE_SQL = """
UPDATE archive.message SET deleted_at = %s, updated_at = now()
WHERE channel_id = %s AND ts = %s AND deleted_at IS NULL
"""

LOCK_SQL = "SELECT pg_advisory_xact_lock(hashtext(%s))"

def stamp(ts):
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def body_of(envelope):
    if envelope.get("type") not in (None, "message"):
        return None
    if envelope.get("subtype") == DELETED_SUBTYPE:
        return None
    if envelope.get("subtype") == CHANGED:
        changed = envelope.get("message")
        return changed if isinstance(changed, dict) else None
    return envelope


def lock_channel(conn, channel_id):
    with conn.cursor() as cur:
        cur.execute(LOCK_SQL, (channel_id,))


def message_row(channel_id, ts, revision, envelope, measured):
    body = body_of(envelope)
    if body is None:
        return None

    posted = stamp(ts)
    if posted is None:
        return None

    thread_root = body.get("thread_ts")
    edited = body.get("edited") or {}
    stats = measured or {}
    wrapper = envelope.get("subtype")
    subtype = body.get("subtype") or (None if wrapper in WRAPPERS else wrapper)
    return (
        channel_id, ts, revision, posted,
        body.get("user") or body.get("bot_id") or envelope.get("user"),
        author_kind(body),
        body.get("bot_id"),
        body.get("app_id"),
        body.get("parent_user_id"),
        subtype,
        thread_root,
        bool(thread_root) and thread_root != ts,
        body.get("subtype") == "thread_broadcast",
        body.get("reply_count"),
        body.get("reply_users_count"),
        body.get("latest_reply"),
        stats.get("text_length"),
        stats.get("has_text"),
        stats.get("block_count"),
        stats.get("attachment_count"),
        stats.get("file_count"),
        stats.get("mention_count"),
        stats.get("mentioned_ids"),
        stats.get("is_question"),
        stats.get("is_substantive"),
        stats.get("has_link"),
        stats.get("emoji_only"),
        stats.get("reaction_count"),
        stats.get("reactor_count"),
        stamp(edited.get("ts")) if edited.get("ts") else None,
        edited.get("user"),
        body.get("client_msg_id"),
        body.get("team") or body.get("source_team"),
    )


def record_many(conn, channel_id, entries, method, transport, settled, on_reject=None):
    def reject(ts, reason):
        if on_reject is not None:
            on_reject(ts, reason)

    messages = []
    for ts, envelope, measured in entries:
        if not channel_id or not ts or not isinstance(envelope, dict):
            reject(ts, "no channel, no ts, or the envelope is not an object")
            continue
        if body_of(envelope) is None:
            reject(ts, "the envelope carries no message body")
            continue
        row_values = message_row(channel_id, ts, FETCHED, envelope, measured)
        if row_values is None:
            reject(ts, "the envelope would not build a message row")
            continue
        messages.append((*row_values, settled))
    if not messages:
        return 0

    lock_channel(conn, channel_id)
    with conn.cursor() as cur:
        cur.executemany(MESSAGE_SQL, [dict(zip(COLUMNS, row)) for row in messages])
        member_seen.posted(cur, member_posts(messages))
    return len(messages)


def from_api_many(conn, channel_id, messages, method, transport, on_reject=None):
    return record_many(
        conn, channel_id,
        [(message.get("ts"), redact(message), normalize(message)) for message in messages],
        method, transport, True, on_reject=on_reject)


def record(conn, channel_id, ts, envelope, measured, method, transport, settled):
    return record_many(conn, channel_id, [(ts, envelope, measured)], method, transport,
                       settled) == 1


def from_api(conn, channel_id, message, method, transport):
    ts = message.get("ts")
    return record(conn, channel_id, ts, redact(message), normalize(message),
                  method, transport, True)


def from_event(conn, channel_id, message):
    return record(conn, channel_id, message.get("ts"), redact(message), normalize(message),
                  EVENT, EVENT, False)


def edit_values(channel_id, message):
    measured = normalize(message)
    edit = message.get("edited") or {}
    values = {name: measured.get(name) for name in EDIT_MEASURES}
    values.update(
        channel_id=channel_id,
        ts=message.get("ts"),
        file_count=measured["file_count"] if "files" in message else None,
        edited_at=stamp(edit.get("ts")) if edit.get("ts") else None,
        edited_by=edit.get("user"),
    )
    return values


def edited(conn, channel_id, message):
    ts = message.get("ts")
    if not channel_id or stamp(ts) is None:
        return False

    with conn.cursor() as cur:
        cur.execute(EDIT_SQL, edit_values(channel_id, message))
        if cur.rowcount:
            return True
        held = cur.execute(HELD_SQL, (channel_id, ts)).fetchone()
    return False if held else from_event(conn, channel_id, message)


def deleted(conn, channel_id, ts, at=None):
    if not channel_id or stamp(ts) is None:
        return False

    with conn.cursor() as cur:
        cur.execute(DELETE_SQL, (stamp(at) or datetime.now(timezone.utc), channel_id, ts))
        return cur.rowcount == 1
