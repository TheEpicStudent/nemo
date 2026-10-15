import datetime as dt
import json

from bot.core.formatting import short_end

CALLBACK = "thread_slowmode"
DISABLED_CALLBACK = "thread_slowmode_disabled"

UNTIL = "slowmode_until"
SECONDS = "slowmode_seconds"
REASON = "slowmode_reason"
EXEMPT = "slowmode_exempt"
DISABLE = "slowmode_off"

TITLE = "Slow mode"
REASON_LIMIT = 500
SHORTEST = 1
LONGEST = 3600
STARTING_SECONDS = 30


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


def summary(seconds, expires_at):
    return f"{cooldown(seconds)} cooldown · {ends(expires_at)}"


def plain(text):
    return {"type": "plain_text", "text": text}


def until_block(expires_at=None):
    element = {"type": "datetimepicker", "action_id": UNTIL}
    if expires_at:
        element["initial_date_time"] = int(expires_at.timestamp())
    return {"type": "input", "block_id": UNTIL, "optional": True,
            "label": plain("End"), "element": element}


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


def status_block(current):
    return {
        "type": "section",
        "text": {"type": "mrkdwn",
                 "text": f"*Enabled* · set by <@{current['opened_by']}> · {ends(current['expires_at'])}"},
        "accessory": {
            "type": "button", "action_id": DISABLE, "style": "danger", "text": plain("Disable"),
            "confirm": {"title": plain("Disable slow mode"),
                        "text": {"type": "mrkdwn", "text": "Disable slow mode in this thread."},
                        "confirm": plain("Disable"), "deny": plain("Cancel"), "style": "danger"},
        },
    }


def build_view(channel_id, thread_ts, current=None):
    blocks = [
        until_block(current and current["expires_at"]),
        seconds_block(current and current["seconds"]),
        reason_block(current and current["reason"]),
        exempt_block(current["exempt"] if current else ()),
    ]
    if current:
        blocks.insert(0, status_block(current))
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
    picked = values.get(UNTIL, {}).get(UNTIL, {}).get("selected_date_time")
    return {
        "expires_at": dt.datetime.fromtimestamp(picked, dt.UTC) if picked else None,
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


def validation_errors(values, now=None):
    if values["expires_at"] and values["expires_at"] <= (now or dt.datetime.now(dt.UTC)):
        return {UNTIL: "Pick a time in the future."}
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


def confirmation(verb, seconds, expires_at, reason):
    return f"Slow mode {verb} · {summary(seconds, expires_at)} · Reason: {reason}"


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
