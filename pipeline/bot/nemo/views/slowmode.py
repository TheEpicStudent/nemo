import datetime as dt
import json

from bot.core.formatting import short_end

CALLBACK = "thread_slowmode"
DISABLED_CALLBACK = "thread_slowmode_disabled"

UNTIL = "slowmode_until"
DURATION = "slowmode_duration"
EXTEND = "slowmode_extend"
SECONDS = "slowmode_seconds"
REASON = "slowmode_reason"
EXEMPT = "slowmode_exempt"
DISABLE = "slowmode_off"

TITLE = "Slow mode"
REASON_LIMIT = 500
SHORTEST = 1
LONGEST = 3600
STARTING_SECONDS = 30

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


def metadata(channel_id, thread_ts):
    return json.dumps({"channel_id": channel_id, "thread_ts": thread_ts})


def opened(view):
    try:
        values = json.loads(view.get("private_metadata") or "{}")
    except ValueError:
        return None, None
    return values.get("channel_id"), values.get("thread_ts")


def cooldown(seconds):
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def ends(expires_at):
    return f"ends {short_end(expires_at)}" if expires_at else "no end date"


def remaining(expires_at, now=None):
    if not expires_at:
        return "no end date"
    seconds = max(int((expires_at - (now or dt.datetime.now(dt.UTC))).total_seconds()), 0)
    if seconds >= 86400:
        left = f"{seconds // 86400}d {seconds % 86400 // 3600}h"
    elif seconds >= 3600:
        left = f"{seconds // 3600}h {seconds % 3600 // 60}m"
    else:
        left = f"{max(seconds // 60, 1)}m"
    return f"ends in {left} · {short_end(expires_at)}"


def summary(seconds, expires_at):
    return f"{cooldown(seconds)} cooldown · {ends(expires_at)}"


def plain(text):
    return {"type": "plain_text", "text": text}


def option(key, label):
    return {"text": plain(label), "value": key}


def length_options(prefix=""):
    return [option(key, f"{prefix}{label}") for key, (label, _length) in DURATIONS.items()] + \
        [option(CUSTOM, "Custom end")]


def duration_block():
    return {"type": "input", "block_id": DURATION, "optional": True, "dispatch_action": True,
            "label": plain("Duration"),
            "element": {"type": "static_select", "action_id": DURATION,
                        "placeholder": plain("No end"), "options": length_options()}}


def extend_block():
    return {"type": "input", "block_id": EXTEND, "optional": True, "dispatch_action": True,
            "label": plain("Extend by"),
            "element": {"type": "static_select", "action_id": EXTEND,
                        "placeholder": plain("Select"), "options": length_options("+")}}


def until_block():
    return {"type": "input", "block_id": UNTIL, "label": plain("End"),
            "element": {"type": "datetimepicker", "action_id": UNTIL}}


def seconds_block(seconds=None):
    return {"type": "input", "block_id": SECONDS, "label": plain("Cooldown (seconds)"),
            "element": {"type": "number_input", "action_id": SECONDS, "is_decimal_allowed": False,
                        "min_value": str(SHORTEST), "max_value": str(LONGEST),
                        "initial_value": str(seconds or STARTING_SECONDS)}}


def reason_block(reason=None):
    element = {"type": "plain_text_input", "action_id": REASON, "multiline": True,
               "max_length": REASON_LIMIT}
    if reason:
        element["initial_value"] = reason
    return {"type": "input", "block_id": REASON, "label": plain("Reason"), "element": element}


def exempt_block(user_ids=()):
    element = {"type": "multi_users_select", "action_id": EXEMPT}
    if user_ids:
        element["initial_users"] = list(user_ids)
    return {"type": "input", "block_id": EXEMPT, "optional": True,
            "label": plain("Exempt members"), "element": element}


def status_block(current, now=None):
    return {
        "type": "section",
        "text": {"type": "mrkdwn",
                 "text": f"*Enabled* · {remaining(current['expires_at'], now)} · "
                         f"set by <@{current['opened_by']}>"},
        "accessory": {
            "type": "button", "action_id": DISABLE, "style": "danger", "text": plain("Disable"),
            "confirm": {"title": plain("Disable slow mode"),
                        "text": {"type": "mrkdwn", "text": "Disable slow mode in this thread."},
                        "confirm": plain("Disable"), "deny": plain("Cancel"), "style": "danger"},
        },
    }


def build_view(channel_id, thread_ts, current=None, custom=False, now=None):
    blocks = [status_block(current, now), extend_block()] if current else [duration_block()]
    if custom:
        blocks.append(until_block())
    blocks += [
        seconds_block(current and current["seconds"]),
        reason_block(current and current["reason"]),
        exempt_block(current["exempt"] if current else ()),
    ]
    return {
        "type": "modal",
        "callback_id": CALLBACK,
        "private_metadata": metadata(channel_id, thread_ts),
        "title": plain(TITLE),
        "submit": plain("Save" if current else "Enable"),
        "close": plain("Cancel"),
        "blocks": blocks,
    }


def disabled_view():
    return {
        "type": "modal",
        "callback_id": DISABLED_CALLBACK,
        "title": plain(TITLE),
        "close": plain("Close"),
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "*Disabled*"}}],
    }


def chosen(values, block_id):
    return ((values.get(block_id, {}).get(block_id, {}).get("selected_option") or {}).get("value"))


def submitted_values(state):
    values = state.get("values", {})
    picked = values.get(UNTIL, {}).get(UNTIL, {}).get("selected_date_time")
    return {
        "starting": EXTEND not in values,
        "duration": chosen(values, DURATION),
        "extend": chosen(values, EXTEND),
        "until": dt.datetime.fromtimestamp(picked, dt.UTC) if picked else None,
        "seconds": values.get(SECONDS, {}).get(SECONDS, {}).get("value"),
        "reason": (values.get(REASON, {}).get(REASON, {}).get("value") or "").strip(),
        "exempt": values.get(EXEMPT, {}).get(EXEMPT, {}).get("selected_users") or [],
    }


def seconds_of(values):
    try:
        seconds = int(str(values.get("seconds") or "").strip())
    except ValueError:
        return None
    return seconds if SHORTEST <= seconds <= LONGEST else None


def length_key(values):
    return values["duration"] if values["starting"] else values["extend"]


def new_end(values, current=None, now=None):
    now = now or dt.datetime.now(dt.UTC)
    key = length_key(values)
    if key == CUSTOM:
        return values["until"]
    if key in DURATIONS:
        start = now if values["starting"] or not current else (current["expires_at"] or now)
        return max(start, now) + DURATIONS[key][1]
    if values["starting"]:
        return None
    return current["expires_at"] if current else None


def validation_errors(values, now=None):
    now = now or dt.datetime.now(dt.UTC)
    key = length_key(values)
    if key == CUSTOM and not values["until"]:
        return {UNTIL: "Select the end."}
    if key == CUSTOM and values["until"] <= now:
        return {UNTIL: "Select a time in the future."}
    if seconds_of(values) is None:
        return {SECONDS: f"Enter {SHORTEST} to {LONGEST} seconds."}
    if not values["reason"]:
        return {REASON: "Add a reason."}
    return None


def notice(seconds, expires_at, by):
    text = f"*Slow mode enabled* · {summary(seconds, expires_at)}"
    return {
        "text": text,
        "blocks": [
            {"type": "section", "text": {"type": "mrkdwn", "text": text}},
            {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Fire Department · <@{by}>"}]},
        ],
    }


def confirmation(verb, seconds, expires_at, reason, channel_id=None):
    where = f" in <#{channel_id}>" if channel_id else ""
    return f"Slow mode {verb}{where} · {summary(seconds, expires_at)} · Reason: {reason}"


def held_back(seconds_remaining, body, in_thread):
    what = "reply" if in_thread else "message"
    text = f"*Slow mode* · next {what} in {wait(seconds_remaining)}"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if body:
        blocks.append({"type": "rich_text", "elements": [{
            "type": "rich_text_preformatted", "elements": [{"type": "text", "text": body}],
        }]})
    return {"text": text, "blocks": blocks}


def wait(seconds):
    if seconds < 60:
        return f"{seconds}s"
    return f"{(seconds + 59) // 60}m"
