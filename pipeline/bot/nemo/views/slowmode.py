import datetime as dt
import json

from bot.nemo.views import lengths

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
MIN_SECONDS = 1
MAX_SECONDS = 3600
DEFAULT_SECONDS = 30

CUSTOM = lengths.CUSTOM
DURATIONS = lengths.DURATIONS


def metadata(channel_id, thread_ts):
    return json.dumps({"channel_id": channel_id, "thread_ts": thread_ts})


def parse_metadata(view):
    try:
        values = json.loads(view.get("private_metadata") or "{}")
    except ValueError:
        return None, None
    return values.get("channel_id"), values.get("thread_ts")


def cooldown(seconds):
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def summary(seconds, expires_at):
    return f"{cooldown(seconds)} cooldown · {lengths.ends(expires_at)}"


plain = lengths.plain


def duration_block():
    return lengths.picker(DURATION, "Duration", "No end", optional=True)


def extend_block():
    return lengths.picker(EXTEND, "Extend by", "Select", optional=True, prefix="+")


def until_block():
    return lengths.end_picker(UNTIL)


def seconds_block(seconds=None):
    return {"type": "input", "block_id": SECONDS, "label": plain("Cooldown (seconds)"),
            "element": {"type": "number_input", "action_id": SECONDS, "is_decimal_allowed": False,
                        "min_value": str(MIN_SECONDS), "max_value": str(MAX_SECONDS),
                        "initial_value": str(seconds or DEFAULT_SECONDS)}}


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
                 "text": f"*Enabled* · {lengths.remaining(current['expires_at'], now)} · "
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


def submitted_values(state):
    values = state.get("values", {})
    return {
        "starting": EXTEND not in values,
        "duration": lengths.selected_value(values, DURATION),
        "extend": lengths.selected_value(values, EXTEND),
        "until": lengths.selected_datetime(values, UNTIL),
        "seconds": values.get(SECONDS, {}).get(SECONDS, {}).get("value"),
        "reason": (values.get(REASON, {}).get(REASON, {}).get("value") or "").strip(),
        "exempt": values.get(EXEMPT, {}).get(EXEMPT, {}).get("selected_users") or [],
    }


def parse_seconds(values):
    try:
        seconds = int(str(values.get("seconds") or "").strip())
    except ValueError:
        return None
    return seconds if MIN_SECONDS <= seconds <= MAX_SECONDS else None


def length_key(values):
    return values["duration"] if values["starting"] else values["extend"]


def new_end(values, current=None, now=None):
    key = length_key(values)
    start = None if values["starting"] or not current else current["expires_at"]
    ends = lengths.end_from(key, values["until"], start, now)
    if ends or values["starting"]:
        return ends
    return current["expires_at"] if current else None


def validation_errors(values, now=None):
    now = now or dt.datetime.now(dt.UTC)
    errors = lengths.end_errors(length_key(values), values["until"], UNTIL, now)
    if errors:
        return errors
    if parse_seconds(values) is None:
        return {SECONDS: f"Enter {MIN_SECONDS} to {MAX_SECONDS} seconds."}
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


def removal_notice(seconds_remaining, body, in_thread):
    what = "reply" if in_thread else "message"
    text = f"*Slow mode* · next {what} in {format_wait(seconds_remaining)}"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if body:
        blocks.append({"type": "rich_text", "elements": [{
            "type": "rich_text_preformatted", "elements": [{"type": "text", "text": body}],
        }]})
    return {"text": text, "blocks": blocks}


def format_wait(seconds):
    if seconds < 60:
        return f"{seconds}s"
    return f"{(seconds + 59) // 60}m"
