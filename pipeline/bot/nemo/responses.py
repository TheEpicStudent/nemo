import logging
import threading

log = logging.getLogger("bot.nemo")

AUTORESPONSE_ON = "nemo.autoresponse_on"
AUTORESPONSE_EMOJI = "nemo.autoresponse_emoji"
AUTORESPONSE_CHANNEL = "nemo.autoresponse_channel"
AUTORESPONSE_BODY = "nemo.autoresponse_body"
AUTORESPONSE_COOLDOWN = "nemo.autoresponse_cooldown_days"
UNSUB_SHIELD_ON = "nemo.unsub_shield_on"
UNSUB_SHIELD_LINK = "nemo.unsub_shield_link"

KEYS = (
    AUTORESPONSE_ON, AUTORESPONSE_EMOJI, AUTORESPONSE_CHANNEL, AUTORESPONSE_BODY,
    AUTORESPONSE_COOLDOWN, UNSUB_SHIELD_ON, UNSUB_SHIELD_LINK,
)

DEFAULT_COOLDOWN_DAYS = 7
MAX_COOLDOWN_DAYS = 365

SETTINGS_BY_KEY = "SELECT key, value FROM fd.app_settings WHERE key = ANY(%s)"

CLAIM_COOLDOWN = """
INSERT INTO fd.autoresponse_cooldown (user_id, sent_at)
VALUES (%s, now())
ON CONFLICT (user_id) DO UPDATE SET sent_at = now()
WHERE fd.autoresponse_cooldown.sent_at <= now() - make_interval(days => %s)
RETURNING sent_at
"""

_settings = {}
_loaded = False
_lock = threading.Lock()


def refresh(conn):
    global _loaded
    settings = dict(conn.execute(SETTINGS_BY_KEY, (list(KEYS),)).fetchall())
    with _lock:
        _settings.clear()
        _settings.update(settings)
        _loaded = True
    return len(settings)


def setting(key):
    with _lock:
        if not _loaded:
            return None
        return (_settings.get(key) or "").strip()


MEMBER_PLACEHOLDER = "{member}"


def render_body(user_id):
    return (setting(AUTORESPONSE_BODY) or "").replace(MEMBER_PLACEHOLDER, f"<@{user_id}>")


def is_on(key):
    return setting(key) == "on"


def setting_list(key):
    value = setting(key) or ""
    return [one.strip() for one in value.split(",") if one.strip()]


def cooldown_days():
    try:
        days = int(setting(AUTORESPONSE_COOLDOWN) or 0)
    except ValueError:
        days = 0
    return days if 1 <= days <= MAX_COOLDOWN_DAYS else DEFAULT_COOLDOWN_DAYS


def applies_to(channel_id, emoji):
    if not is_on(AUTORESPONSE_ON):
        return False
    if not setting(AUTORESPONSE_BODY):
        return False
    if channel_id != setting(AUTORESPONSE_CHANNEL):
        return False
    return emoji in setting_list(AUTORESPONSE_EMOJI)


def claim_cooldown(conn, user_id):
    return conn.execute(CLAIM_COOLDOWN, (user_id, cooldown_days())).fetchone()


def unsub_shield_enabled():
    return is_on(UNSUB_SHIELD_ON)
