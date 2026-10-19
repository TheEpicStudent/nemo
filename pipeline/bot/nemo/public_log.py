import logging
import re
import threading

import yaml

from bot.core import session
from bot.nemo import channels, guard_actions, guard_commands, internal_log, memberguards
from bot.nemo.views import lengths
from bot.nemo.views.activity import message_url
from lib.paths import PUBLIC_LOG_EVENTS_FILE

log = logging.getLogger("bot.nemo")

CURSOR_NAME = "public_audit"
CHANNEL_SETTING = channels.PUBLIC_LOG
ENTITY_TYPES = ["member_guard", "thread_guard"]
VERBS = ["opened", "lifted"]
BATCH = 50
NO_REASON = "n/a"
SYSTEM_LABEL = "Nemo"
VARIABLE = re.compile(r"\{(\w+)\}")

EVENTS = yaml.safe_load(PUBLIC_LOG_EVENTS_FILE.read_text())["events"]
MEMBER_EVENTS = {"shush": "shush", "channel_ban": "channel_ban", "deactivation": "deactivation"}

MEMBER_GUARD = """
SELECT kind, subject_id, channel_id, reason, expires_at
FROM fd.member_guards WHERE id = %s
"""

THREAD_GUARD = """
SELECT kind, channel_id, thread_ts, reason, expires_at, state, opened_by, deleted_count
FROM fd.thread_guards WHERE id = %s
"""

SETTINGS_BY_KEY = "SELECT key, value FROM fd.app_settings WHERE key = ANY(%s)"

_lock = threading.Lock()


def enabled_key(event):
    return f"nemo.public_log.{event}.on"


def template_key(event):
    return f"nemo.public_log.{event}.template"


def setting_keys():
    keys = [CHANNEL_SETTING]
    for event in EVENTS:
        keys += [enabled_key(event), template_key(event)]
    return keys


def load_settings(conn):
    return dict(conn.execute(SETTINGS_BY_KEY, (setting_keys(),)).fetchall())


def is_enabled(settings, event):
    value = (settings.get(enabled_key(event)) or "").strip().lower()
    if value in ("on", "off"):
        return value == "on"
    return bool(EVENTS[event]["enabled"])


def template_for(settings, event):
    return (settings.get(template_key(event)) or "").strip() or EVENTS[event]["template"]


def render(template, values):
    return VARIABLE.sub(lambda found: str(values.get(found.group(1), found.group(0))), template)


def actor_label(actor):
    return SYSTEM_LABEL if actor in internal_log.SYSTEM_ACTORS else f"<@{actor}>"


def member_values(entry, row):
    kind, subject_id, channel_id, reason, expires_at = row
    event = MEMBER_EVENTS.get(kind)
    if event is None or entry["verb"] != "opened":
        return None, None
    return event, {
        "member": f"<@{subject_id}>",
        "admin": actor_label(entry["actor"]),
        "channel": f"<#{channel_id}>" if channel_id else "",
        "reason": reason or NO_REASON,
        "ends": lengths.logged_ends(expires_at),
    }


def thread_values(entry, row):
    kind, channel_id, thread_ts, reason, expires_at, state, opened_by, deleted_count = row
    if kind == "lock" and entry["verb"] == "opened":
        return "lock", {
            "admin": actor_label(entry["actor"]),
            "channel": f"<#{channel_id}>",
            "thread": message_url(channel_id, thread_ts),
            "reason": reason or NO_REASON,
            "ends": lengths.logged_ends(expires_at),
        }
    if kind == "destroy" and entry["verb"] == "lifted" and state == "done":
        return "destroy", {
            "admin": actor_label(opened_by),
            "channel": f"<#{channel_id}>",
            "thread": message_url(channel_id, thread_ts),
            "count": deleted_count,
            "archive": guard_actions.archive_url(channel_id, thread_ts) or "",
        }
    return None, None


BUILDERS = {
    "member_guard": (MEMBER_GUARD, member_values),
    "thread_guard": (THREAD_GUARD, thread_values),
}


def event_for(conn, entry):
    sql, build = BUILDERS[entry["entity_type"]]
    row = conn.execute(sql, (entry["entity_id"],)).fetchone()
    return build(entry, row) if row else (None, None)


def audit_events(conn):
    entries = conn.execute(
        internal_log.AUDIT_ENTRIES, (internal_log.cursor(conn, CURSOR_NAME), ENTITY_TYPES, VERBS, BATCH)
    ).fetchall()
    events = []
    for one in entries:
        entry = dict(zip(("id", "actor", "entity_type", "entity_id", "verb", "before", "after"), one))
        events.append((entry["id"], *event_for(conn, entry)))
    return events


def ensure_read_only(client, conn, channel_id):
    try:
        guard_commands.open_or_tune(client, conn, guard_commands.READONLY, channel_id,
                                    {"threads": True}, "", memberguards.NEMO)
    except Exception as failure:
        log.warning("nemo: public log channel %s not made read-only: %s", channel_id, failure)


def post_text(client, conn, channel_id, text):
    ensure_read_only(client, conn, channel_id)
    client.chat_postMessage(channel=channel_id, text=text, unfurl_links=False, unfurl_media=False)


def drain(client):
    if not _lock.acquire(blocking=False):
        return 0
    try:
        with session() as conn:
            settings = load_settings(conn)
            events = audit_events(conn)
        channel_id = (settings.get(CHANNEL_SETTING) or "").strip()

        handled = 0
        for entry_id, event, values in events:
            if event and channel_id and is_enabled(settings, event):
                try:
                    with session() as conn:
                        post_text(client, conn, channel_id, render(template_for(settings, event), values))
                except Exception as failure:
                    log.warning("nemo: public log entry %s %s not posted: %s", entry_id, event, failure)
                    break
            internal_log.advance_cursor(CURSOR_NAME, entry_id)
            handled += 1
        return handled
    finally:
        _lock.release()
