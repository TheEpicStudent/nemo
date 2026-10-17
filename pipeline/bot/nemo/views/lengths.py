import datetime as dt

from bot.core.formatting import short_end

CUSTOM = "custom"
DURATIONS = {
    "15m": ("15 minutes", dt.timedelta(minutes=15)),
    "30m": ("30 minutes", dt.timedelta(minutes=30)),
    "1h": ("1 hour", dt.timedelta(hours=1)),
    "2h": ("2 hours", dt.timedelta(hours=2)),
    "6h": ("6 hours", dt.timedelta(hours=6)),
    "12h": ("12 hours", dt.timedelta(hours=12)),
    "24h": ("24 hours", dt.timedelta(hours=24)),
}


def plain(text):
    return {"type": "plain_text", "text": text}


def options(prefix=""):
    return [{"text": plain(f"{prefix}{label}"), "value": key}
            for key, (label, _length) in DURATIONS.items()] + \
        [{"text": plain("Custom end"), "value": CUSTOM}]


def picker(block_id, label, placeholder, optional, prefix=""):
    return {"type": "input", "block_id": block_id, "optional": optional, "dispatch_action": True,
            "label": plain(label),
            "element": {"type": "static_select", "action_id": block_id,
                        "placeholder": plain(placeholder), "options": options(prefix)}}


def end_picker(block_id):
    return {"type": "input", "block_id": block_id, "label": plain("End"),
            "element": {"type": "datetimepicker", "action_id": block_id}}


def selected_value(values, block_id):
    return (values.get(block_id, {}).get(block_id, {}).get("selected_option") or {}).get("value")


def selected_datetime(values, block_id):
    picked = values.get(block_id, {}).get(block_id, {}).get("selected_date_time")
    return dt.datetime.fromtimestamp(picked, dt.UTC) if picked else None


def ends(expires_at):
    return f"until {short_end(expires_at)}" if expires_at else "with no end date"


def span(seconds):
    seconds = max(seconds, 0)
    if seconds >= 86400:
        return f"{seconds // 86400}d {seconds % 86400 // 3600}h"
    if seconds >= 3600:
        return f"{seconds // 3600}h {seconds % 3600 // 60}m"
    return f"{max(seconds // 60, 1)}m"


def remaining(expires_at, now=None):
    if not expires_at:
        return "with no end date"
    seconds = int((expires_at - (now or dt.datetime.now(dt.UTC))).total_seconds())
    return f"until {short_end(expires_at)} ({span(seconds)} left)"


def end_from(key, until, start=None, now=None):
    now = now or dt.datetime.now(dt.UTC)
    if key == CUSTOM:
        return until
    if key in DURATIONS:
        return max(start or now, now) + DURATIONS[key][1]
    return None


def end_errors(key, until, block_id, now=None):
    if key != CUSTOM:
        return None
    if not until:
        return {block_id: "Select the end."}
    if until <= (now or dt.datetime.now(dt.UTC)):
        return {block_id: "Select a time in the future."}
    return None
