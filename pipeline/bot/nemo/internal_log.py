import logging
import threading

from bot.core import session
from bot.nemo import channel, memberguards
from bot.nemo.enforcement.sweep import LAPSED_BECAUSE
from bot.nemo.guard_notices import quoted
from bot.nemo.views import lengths
from bot.nemo.views.activity import message_url
from bot.nemo.views.slowmode import cooldown

log = logging.getLogger("bot.nemo")

AUDIT = "audit"
AUTOMOD = "automod"
BATCH = 50
REPLACED_BY_DESTROY = "replaced by a destroy"
NOT_PEOPLE = (None, "system", memberguards.NEMO)

ENTITY_TYPES = ["member_guard", "channel_guard", "channel_allow", "thread_guard"]
VERBS = ["opened", "lifted", "extended", "tuned", "added", "removed"]

CURSOR = "SELECT last_id FROM fd.log_cursors WHERE name = %s"
MOVE_CURSOR = "UPDATE fd.log_cursors SET last_id = %s, updated_at = now() WHERE name = %s"

AUDIT_AFTER = """
SELECT id, actor_user_id, entity_type, entity_id, verb, before, after
FROM fd.audit
WHERE id > %s AND occurred_at > now() - interval '7 days'
  AND entity_type = ANY(%s) AND verb = ANY(%s)
ORDER BY id
LIMIT %s
"""

AUTOMOD_AFTER = """
SELECT id, word, user_id, channel_id, permalink, body
FROM fd.automod_matches
WHERE id > %s
ORDER BY id
LIMIT %s
"""

MEMBER_GUARD = """
SELECT kind, subject_id, channel_id, reason, expires_at, lift_reason
FROM fd.member_guards WHERE id = %s
"""

CHANNEL_GUARD = """
SELECT kind, channel_id, thread_ts, settings, reason, expires_at
FROM fd.channel_guards WHERE id = %s
"""

THREAD_GUARD = """
SELECT kind, channel_id, thread_ts, reason, expires_at, state, error
FROM fd.thread_guards WHERE id = %s
"""

MEMBER_LABELS = {"shush": "Shush", "channel_ban": "Channel ban", "deactivation": "Deactivation"}
CHANNEL_LABELS = {"slowmode": "Slow mode", "readonly": "Read-only", "account_age": "New-account gate",
                  "bot_allowlist": "Bot allow list"}

_lock = threading.Lock()


def by(actor):
    return f" · by <@{actor}>" if actor not in NOT_PEOPLE else ""


def reason_part(reason):
    return f" · Reason: {reason}" if reason else ""


def thread_link(channel_id, thread_ts):
    return f"<{message_url(channel_id, thread_ts)}|thread>"


def member_line(entry, row):
    kind, subject_id, channel_id, reason, expires_at, lift_reason = row
    label = MEMBER_LABELS.get(kind, kind)
    who = f"<@{subject_id}>" + (f" · <#{channel_id}>" if channel_id else "")
    verb, actor, after = entry["verb"], entry["actor"], entry["after"] or {}
    if verb == "opened":
        return f"{label} · {who} · {lengths.ends(expires_at)}{reason_part(reason)}{by(actor)}"
    if verb == "extended":
        return f"{label} extended · {who} · {lengths.ends(expires_at)}{by(actor)}"
    if verb == "lifted":
        why = after.get("lift_reason") or lift_reason
        if why == LAPSED_BECAUSE or actor in NOT_PEOPLE:
            return f"{label} ended · {who}"
        return f"{label} lifted · {who}{reason_part(why)}{by(actor)}"
    return None


def channel_where(channel_id, thread_ts):
    return f"<#{channel_id}>" + (f" · {thread_link(channel_id, thread_ts)}" if thread_ts else "")


def channel_details(kind, settings, expires_at):
    settings = settings or {}
    if kind == "slowmode":
        parts = [f"{cooldown(int(settings.get('seconds') or 0))} cooldown", lengths.ends(expires_at)]
        return " · " + " · ".join(parts + (["threads"] if settings.get("threads") else []))
    if kind == "account_age":
        return f" · {int(settings.get('min_age_days') or 0)} days"
    if kind == "readonly" and settings.get("threads"):
        return " · threads"
    return ""


def channel_line(entry, row):
    kind, channel_id, thread_ts, settings, reason, expires_at = row
    label = CHANNEL_LABELS.get(kind, kind)
    where = channel_where(channel_id, thread_ts)
    verb, actor = entry["verb"], entry["actor"]
    if verb == "opened":
        return f"{label} enabled · {where}{channel_details(kind, settings, expires_at)}{reason_part(reason)}{by(actor)}"
    if verb == "tuned":
        return f"{label} updated · {where}{channel_details(kind, settings, expires_at)}{by(actor)}"
    if verb == "extended":
        return f"{label} extended · {where} · {lengths.ends(expires_at)}{by(actor)}"
    if verb == "lifted":
        if actor in NOT_PEOPLE:
            return f"{label} ended · {where}"
        return f"{label} disabled · {where}{by(actor)}"
    return None


def allow_line(entry, row):
    kind, channel_id, thread_ts, _settings, _reason, _expires_at = row
    subject_id = (entry["after"] or {}).get("subject_id") or (entry["before"] or {}).get("subject_id")
    if not subject_id:
        return None
    where = channel_where(channel_id, thread_ts)
    if kind == "bot_allowlist":
        verb = "Bot allowed" if entry["verb"] == "added" else "Bot removed from allow list"
        return f"{verb} · <@{subject_id}> · {where}{by(entry['actor'])}"
    verb = "Exemption added" if entry["verb"] == "added" else "Exemption removed"
    return f"{verb} · <@{subject_id}> · {CHANNEL_LABELS.get(kind, kind)} · {where}{by(entry['actor'])}"


def thread_line(entry, row):
    kind, channel_id, thread_ts, reason, expires_at, state, error = row
    if kind != "lock":
        return None
    where = f"<#{channel_id}> · {thread_link(channel_id, thread_ts)}"
    verb, actor = entry["verb"], entry["actor"]
    if verb == "opened":
        return f"Thread locked · {where} · {lengths.ends(expires_at)}{reason_part(reason)}{by(actor)}"
    if verb == "extended":
        return f"Lock extended · {where} · {lengths.ends(expires_at)}{by(actor)}"
    if verb == "lifted":
        if state == "failed" or error == REPLACED_BY_DESTROY:
            return None
        if actor in NOT_PEOPLE:
            return f"Lock ended · {where}"
        return f"Thread unlocked · {where}{by(actor)}"
    return None


ROWS = {
    "member_guard": (MEMBER_GUARD, member_line),
    "channel_guard": (CHANNEL_GUARD, channel_line),
    "channel_allow": (CHANNEL_GUARD, allow_line),
    "thread_guard": (THREAD_GUARD, thread_line),
}


def line_for(conn, entry):
    sql, build = ROWS[entry["entity_type"]]
    row = conn.execute(sql, (entry["entity_id"],)).fetchone()
    return build(entry, row) if row else None


def automod_line(match):
    _match_id, word, user_id, channel_id, permalink, body = match
    link = f" · <{permalink}|message>" if permalink else ""
    return f'Automod · "{word}" · <@{user_id}> · <#{channel_id}>{link}' + quoted(body)


def cursor(conn, name):
    row = conn.execute(CURSOR, (name,)).fetchone()
    return row[0] if row else 0


def move(name, last_id):
    with session() as conn:
        conn.execute(MOVE_CURSOR, (last_id, name))


def post(client, log_channel_id, text):
    client.chat_postMessage(channel=log_channel_id, text=text, unfurl_links=False, unfurl_media=False)


def send(client, name, lines, log_channel_id):
    handled = 0
    for line_id, text in lines:
        if text and log_channel_id:
            try:
                post(client, log_channel_id, text)
            except Exception as failure:
                log.warning("nemo: internal log line %s %s not posted: %s", name, line_id, failure)
                break
        move(name, line_id)
        handled += 1
    return handled


def audit_lines(conn):
    entries = conn.execute(AUDIT_AFTER, (cursor(conn, AUDIT), ENTITY_TYPES, VERBS, BATCH)).fetchall()
    keys = ("id", "actor", "entity_type", "entity_id", "verb", "before", "after")
    return [(one[0], line_for(conn, dict(zip(keys, one)))) for one in entries]


def automod_lines(conn):
    matches = conn.execute(AUTOMOD_AFTER, (cursor(conn, AUTOMOD), BATCH)).fetchall()
    return [(one[0], automod_line(one)) for one in matches]


def drain(client):
    if not _lock.acquire(blocking=False):
        return 0
    try:
        with session() as conn:
            log_channel_id = channel.log_channel(conn)
            audits = audit_lines(conn)
            automods = automod_lines(conn)
        return send(client, AUDIT, audits, log_channel_id) + send(client, AUTOMOD, automods, log_channel_id)
    finally:
        _lock.release()
