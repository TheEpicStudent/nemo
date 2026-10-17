import json

from bot.core import richtext
from bot.nemo.views import lengths

DESTROY_CALLBACK = "thread_destroy"
LOCK_CALLBACK = "thread_lock"
UNLOCKED_CALLBACK = "thread_unlocked"

REASON = "guard_reason"
UNTIL = "guard_until"
NOTE = "guard_note"
NOTE_TEXT = "guard_note_text"
LOCK_DURATION = "lock_duration"
LOCK_EXTEND = "lock_extend"
UNLOCK = "lock_off"
LOCK_TITLE = "Lock thread"

REASON_LIMIT = 500
NOTE_LABEL = "Post note in thread"
TITLE_LIMIT = 24

SIGN_OUT_NOTE = "Sign-out on repeated posts"


def metadata(channel_id, thread_ts):
    return json.dumps({"channel_id": channel_id, "thread_ts": thread_ts})


def parse_metadata(view):
    try:
        values = json.loads(view.get("private_metadata") or "{}")
    except ValueError:
        return None, None
    return values.get("channel_id"), values.get("thread_ts")


def reason_block(value=None):
    element = {
        "type": "plain_text_input",
        "action_id": REASON,
        "multiline": True,
        "max_length": REASON_LIMIT,
    }
    if value:
        element["initial_value"] = value
    return {
        "type": "input",
        "block_id": REASON,
        "label": {"type": "plain_text", "text": "Reason"},
        "element": element,
    }


def note_option():
    return {"text": {"type": "mrkdwn", "text": NOTE_LABEL}, "value": "on"}


def note_block(on):
    element = {"type": "checkboxes", "action_id": NOTE, "options": [note_option()]}
    if on:
        element["initial_options"] = [note_option()]
    return {
        "type": "input",
        "block_id": NOTE,
        "optional": True,
        "dispatch_action": True,
        "label": {"type": "plain_text", "text": "Note"},
        "element": element,
    }


def note_text_block(value=None):
    element = {
        "type": "rich_text_input",
        "action_id": NOTE_TEXT,
        "min_lines": 4,
    }
    if value:
        element["initial_value"] = value
    return {
        "type": "input",
        "block_id": NOTE_TEXT,
        "label": {"type": "plain_text", "text": "Note text"},
        "element": element,
    }


def section_block(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def context_block():
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": SIGN_OUT_NOTE}]}


def destroy_view(channel_id, thread_ts, values=None):
    values = values or {}
    blocks = [
        context_block(),
        reason_block(values.get("reason")),
        note_block(values.get("note")),
    ]
    if values.get("note"):
        blocks.append(note_text_block(values.get("note_body")))

    return {
        "type": "modal",
        "callback_id": DESTROY_CALLBACK,
        "private_metadata": metadata(channel_id, thread_ts),
        "title": {"type": "plain_text", "text": "Destroy thread"[:TITLE_LIMIT]},
        "submit": {"type": "plain_text", "text": "Destroy"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def lock_modal(channel_id, thread_ts, submit, blocks):
    return {
        "type": "modal",
        "callback_id": LOCK_CALLBACK,
        "private_metadata": metadata(channel_id, thread_ts),
        "title": lengths.plain(LOCK_TITLE),
        "submit": lengths.plain(submit),
        "close": lengths.plain("Cancel"),
        "blocks": blocks,
    }


def lock_view(channel_id, thread_ts, custom=False):
    blocks = [lengths.picker(LOCK_DURATION, "Duration", "No end", optional=True)]
    if custom:
        blocks.append(lengths.end_picker(UNTIL))
    blocks.append(reason_block())
    return lock_modal(channel_id, thread_ts, "Lock", blocks)


def lock_status_block(current, now=None):
    return {
        "type": "section",
        "text": {"type": "mrkdwn",
                 "text": f"*Locked* · {lengths.remaining(current['expires_at'], now)} · "
                         f"set by <@{current['opened_by']}>"},
        "accessory": {
            "type": "button", "action_id": UNLOCK, "style": "danger", "text": lengths.plain("Unlock"),
            "confirm": {"title": lengths.plain("Unlock thread"),
                        "text": {"type": "mrkdwn", "text": "Unlock this thread."},
                        "confirm": lengths.plain("Unlock"), "deny": lengths.plain("Cancel"),
                        "style": "danger"},
        },
    }


def locked_view(channel_id, thread_ts, current, custom=False, now=None):
    blocks = [
        lock_status_block(current, now),
        {"type": "context", "elements": [{"type": "mrkdwn", "text": f"Reason: {current['reason']}"}]},
        lengths.picker(LOCK_EXTEND, "Extend by", "Select", optional=False, prefix="+"),
    ]
    if custom:
        blocks.append(lengths.end_picker(UNTIL))
    return lock_modal(channel_id, thread_ts, "Save", blocks)


def unlocked_view():
    return {
        "type": "modal",
        "callback_id": UNLOCKED_CALLBACK,
        "title": lengths.plain(LOCK_TITLE),
        "close": lengths.plain("Close"),
        "blocks": [section_block("*Unlocked*")],
    }


def submitted_values(state):
    values = state.get("values", {})
    checked_options = values.get(NOTE, {}).get(NOTE, {}).get("selected_options") or []
    return {
        "reason": (values.get(REASON, {}).get(REASON, {}).get("value") or "").strip(),
        "starting": LOCK_EXTEND not in values,
        "duration": lengths.selected_value(values, LOCK_DURATION),
        "extend": lengths.selected_value(values, LOCK_EXTEND),
        "until": lengths.selected_datetime(values, UNTIL),
        "note": bool(checked_options),
        "note_body": values.get(NOTE_TEXT, {}).get(NOTE_TEXT, {}).get("rich_text_value"),
    }


def note_text(values):
    return richtext.flatten(values.get("note_body")) if values.get("note") else ""


SIGNS_OUT = "Repeated replies sign you out of Slack"


def lock_notice(expires_at, reason, signs_out=False):
    text = f"*Thread locked* · {lengths.ends(expires_at)} · Reason: {reason}"
    blocks = [section_block(text)]
    if signs_out:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": SIGNS_OUT}]})
    return {"text": text, "blocks": blocks}


def lock_removal_notice(expires_at, body):
    text = f"*Thread locked* · {lengths.ends(expires_at)}"
    blocks = [section_block(text)]
    if body:
        blocks.append({"type": "rich_text", "elements": [{
            "type": "rich_text_preformatted", "elements": [{"type": "text", "text": body}],
        }]})
    return {"text": text, "blocks": blocks}


def lock_key(values):
    return values["duration"] if values["starting"] else values["extend"]


def lock_errors(values, now=None):
    if values["starting"] and not values["reason"]:
        return {REASON: "Add a reason."}
    if not values["starting"] and values["extend"] not in (*lengths.DURATIONS, lengths.CUSTOM):
        return {LOCK_EXTEND: "Select how long to extend."}
    return lengths.end_errors(lock_key(values), values["until"], UNTIL, now)


def lock_end(values, current=None, now=None):
    start = None if values["starting"] or not current else current["expires_at"]
    return lengths.end_from(lock_key(values), values["until"], start, now)


def validation_errors(values):
    if not values.get("reason"):
        return {REASON: "Add a reason."}
    if values.get("note") and not note_text(values):
        return {NOTE_TEXT: "Enter note text"}
    return None
