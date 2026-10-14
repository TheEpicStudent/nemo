import datetime as dt

import yaml

from bot.nemo.views import edit
from lib.paths import ACTIONS_FILE

CALLBACK = "case_action_log"

TARGET = "action_target"
KIND = "action_kind"
RESOLUTION_NOTE = "action_resolution_note"
UNTIL = "action_until"
WHERE = "action_where"
REASON = "action_reason"
CATEGORY = "action_category"
GUARD_STATUS = "action_standing"
SETTLE = "action_settle"

UNGUARDED = "unguarded"
ORPHANED = "orphaned"
ELSEWHERE = "elsewhere"
HERE = "here"

APPLY = "apply"
ADOPT = "adopt"
EXTEND = "extend"
RECORD = "record"

SETTLE_DEFAULT = {
    UNGUARDED: APPLY,
    ORPHANED: ADOPT,
    ELSEWHERE: RECORD,
    HERE: RECORD,
}

REASON_LIMIT = 2000

TABLE = None


def table():
    global TABLE
    if TABLE is None:
        TABLE = yaml.safe_load(ACTIONS_FILE.read_text())["actions"]
    return TABLE


def label(key):
    row = table().get(key)
    return row["label"] if row else key.replace("_", " ")


def needs_expiry(key):
    return bool(table().get(key, {}).get("expires"))


def enforce(key):
    return table().get(key, {}).get("enforce") or {}


def guard_kind(key):
    return enforce(key).get("guard")


def guard_scope(key):
    return enforce(key).get("scope")


def guard_mode(key):
    return enforce(key).get("carry")


def needs_channel(key):
    return table().get(key, {}).get("channel") == "required"


def takes_channel(key):
    return bool(table().get(key, {}).get("channel"))


def choices():
    return [
        {"text": {"type": "plain_text", "text": row["label"]}, "value": key}
        for key, row in table().items()
    ]


def category_choices():
    return [edit.option(label, key) for key, label in edit.categories().items()]


def category_initial_option(selected_key):
    matches = [one for one in category_choices() if one["value"] == selected_key]
    return {"initial_option": matches[0]} if matches else {}


def kind_initial_option(selected_key):
    matches = [one for one in choices() if one["value"] == selected_key]
    return {"initial_option": matches[0]} if matches else {}


def expiry(values):
    on = values.get("expires_on")
    return f"{on} 23:59:59" if on else None


def format_date(at):
    return at.strftime("%-d %b") if at else None


def format_expiry(expires_on):
    return format_date(dt.date.fromisoformat(expires_on)) if expires_on else None


def header_text(values, channel_name=None):
    key = values["type_key"]
    parts = [label(key)]
    if needs_channel(key) and values.get("channel_id"):
        parts.append(f"from #{channel_name}" if channel_name else f"from {values['channel_id']}")
    until = format_expiry(values.get("expires_on"))
    if needs_expiry(key) and until:
        parts.append(f"until {until}")
    return " ".join(parts)


def existing_action_text(guard):
    text = label(guard["kind"]).lower()
    where = guard.get("channel_id")
    return f"{text} in <#{where}>" if where else text


def case_attribution_text(guard, case_id):
    guard_case_id = guard.get("case_id")
    if guard_case_id is None:
        return "with no case"
    if case_id is not None and guard_case_id == case_id:
        return "on this case"
    return f"on *case {guard_case_id}*"


def footnote(guard):
    parts = [f"set by <@{guard['opened_by']}>"]
    since = format_date(guard.get("opened_at"))
    if since:
        parts.append(f"since {since}")
    until = format_date(guard.get("expires_at"))
    parts.append(f"until {until}" if until else "no end date")
    if guard.get("enforced_by") == "by_hand":
        parts.append("manual")
    elif guard.get("enforcement_status") == "failed":
        parts.append("not enforced")
    elif guard.get("enforcement_status") == "pending":
        parts.append("pending")
    return "  ·  ".join(parts)


def existing_guard_blocks(guard_status):
    guard = (guard_status or {}).get("guard")
    if not guard:
        return []

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "<@{}> already has an active {} {}.".format(
                    guard["subject_id"], existing_action_text(guard), case_attribution_text(guard, guard_status.get("case_id"))
                ),
            },
        },
        {
            "type": "context",
            "block_id": GUARD_STATUS,
            "elements": [{"type": "mrkdwn", "text": footnote(guard)}],
        },
    ]


def settle_options(values, guard_status):
    guard_status = guard_status or {}
    if not guard_status.get("enforceable"):
        return []

    reads = guard_status.get("reads") or UNGUARDED
    if reads == UNGUARDED:
        return []
    if reads == ORPHANED:
        return [
            (ADOPT, "Attach it to this case"),
            (RECORD, "Leave it, only log this action"),
        ]

    built = []
    if needs_expiry(values.get("type_key")):
        built.append((EXTEND, "Change its end date to the date above"))
    built.append((RECORD, "Only log this action"))
    return built if len(built) > 1 else []


def settle_blocks(values, guard_status):
    options = settle_options(values, guard_status)
    if not options:
        return []

    reads = (guard_status or {}).get("reads") or UNGUARDED
    selected = values.get("settle")
    if selected not in dict(options):
        selected = SETTLE_DEFAULT.get(reads, RECORD)

    built = [
        {"text": {"type": "plain_text", "text": text}, "value": value}
        for value, text in options
    ]
    matches = [one for one in built if one["value"] == selected]
    return [
        {
            "type": "input",
            "block_id": SETTLE,
            "label": {"type": "plain_text", "text": "Enforcement"},
            "element": {
                "type": "radio_buttons",
                "action_id": SETTLE,
                "options": built,
                **({"initial_option": matches[0]} if matches else {}),
            },
        }
    ]


def initial_values(subjects=(), category=None):
    return {
        "target_user_id": subjects[0] if subjects else None,
        "category_key": category,
    }


def build_blocks(case_id, values, guard_status=None):
    key = values.get("type_key")
    built = [
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": f"*case {case_id}*"}],
        },
        {
            "type": "input",
            "block_id": TARGET,
            "dispatch_action": True,
            "label": {"type": "plain_text", "text": "Member"},
            "element": {
                "type": "users_select",
                "action_id": TARGET,
                "placeholder": {"type": "plain_text", "text": "who this is about"},
                **(
                    {"initial_user": values["target_user_id"]}
                    if values.get("target_user_id")
                    else {}
                ),
            },
        },
        {
            "type": "input",
            "block_id": KIND,
            "dispatch_action": True,
            "label": {"type": "plain_text", "text": "Action"},
            "element": {
                "type": "static_select",
                "action_id": KIND,
                "placeholder": {"type": "plain_text", "text": "pick one"},
                "options": choices(),
                **kind_initial_option(key),
            },
        },
        {
            "type": "input",
            "block_id": RESOLUTION_NOTE,
            "optional": True,
            "label": {"type": "plain_text", "text": "Outcome"},
            "element": {
                "type": "plain_text_input",
                "action_id": RESOLUTION_NOTE,
                "multiline": True,
                "max_length": REASON_LIMIT,
                "placeholder": {"type": "plain_text", "text": "what fixed it, if anything"},
                **(
                    {"initial_value": values["resolution_note"]}
                    if values.get("resolution_note")
                    else {}
                ),
            },
        },
    ]

    built += existing_guard_blocks(guard_status)

    if needs_expiry(key):
        built.append(
            {
                "type": "input",
                "block_id": UNTIL,
                "label": {"type": "plain_text", "text": "Until"},
                "element": {
                    "type": "datepicker",
                    "action_id": UNTIL,
                    **(
                        {"initial_date": values["expires_on"]}
                        if values.get("expires_on")
                        else {}
                    ),
                },
            }
        )

    if takes_channel(key):
        built.append(
            {
                "type": "input",
                "block_id": WHERE,
                "dispatch_action": True,
                "optional": not needs_channel(key),
                "label": {"type": "plain_text", "text": "Channel"},
                "element": {
                    "type": "conversations_select",
                    "action_id": WHERE,
                    "placeholder": {"type": "plain_text", "text": "pick a channel"},
                    **(
                        {"initial_conversation": values["channel_id"]}
                        if values.get("channel_id")
                        else {}
                    ),
                },
            }
        )

    built += settle_blocks(values, guard_status)

    built += [
        {
            "type": "input",
            "block_id": CATEGORY,
            "optional": True,
            "label": {"type": "plain_text", "text": "Violation"},
            "element": {
                "type": "static_select",
                "action_id": CATEGORY,
                "placeholder": {"type": "plain_text", "text": "pick one"},
                "options": category_choices(),
                **category_initial_option(values.get("category_key")),
            },
        },
        {
            "type": "input",
            "block_id": REASON,
            "label": {"type": "plain_text", "text": "Reason"},
            "element": {
                "type": "plain_text_input",
                "action_id": REASON,
                "multiline": True,
                "max_length": REASON_LIMIT,
                "placeholder": {"type": "plain_text", "text": "what they did"},
                **({"initial_value": values["reason"]} if values.get("reason") else {}),
            },
        },
    ]
    return built


def build_view(case_id, subjects=(), category=None, values=None, guard_status=None):
    return {
        "type": "modal",
        "callback_id": CALLBACK,
        "private_metadata": str(case_id),
        "title": {"type": "plain_text", "text": "Log an action"},
        "submit": {"type": "plain_text", "text": "Log"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": build_blocks(case_id, values or initial_values(subjects, category), guard_status),
    }


HEADER_TEXT_LIMIT = 150


def echo_blocks(values, by, channel_name=None):
    built = [
        {
            "type": "header",
            "text": {"type": "plain_text",
                      "text": header_text(values, channel_name)[:HEADER_TEXT_LIMIT]},
        },
        {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"Against <@{values['target_user_id']}> · logged by <@{by}>",
            }],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"> {values['reason']}"},
        },
    ]
    if values.get("resolution_note"):
        built.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"*Outcome:* {values['resolution_note']}",
            }],
        })
    return built


def requires_refresh(values, block_ids, guard_status=None):
    key = values.get("type_key")
    if needs_expiry(key) and UNTIL not in block_ids:
        return True
    if needs_channel(key) and WHERE not in block_ids:
        return True
    if (guard_status or {}).get("guard") and GUARD_STATUS not in block_ids:
        return True
    return bool(settle_options(values, guard_status)) and SETTLE not in block_ids


def submitted_values(view_state):
    values = view_state.get("values", {})
    return {
        "target_user_id": values.get(TARGET, {}).get(TARGET, {}).get("selected_user"),
        "type_key": (
            (values.get(KIND, {}).get(KIND, {}).get("selected_option") or {}).get("value")
        ),
        "resolution_note": (
            values.get(RESOLUTION_NOTE, {}).get(RESOLUTION_NOTE, {}).get("value") or ""
        ).strip(),
        "expires_on": values.get(UNTIL, {}).get(UNTIL, {}).get("selected_date"),
        "channel_id": values.get(WHERE, {}).get(WHERE, {}).get("selected_conversation"),
        "settle": (
            (values.get(SETTLE, {}).get(SETTLE, {}).get("selected_option") or {}).get("value")
        ),
        "reason": (values.get(REASON, {}).get(REASON, {}).get("value") or "").strip(),
        "category_key": (
            (values.get(CATEGORY, {}).get(CATEGORY, {}).get("selected_option") or {})
            .get("value")
        ),
    }


def validation_errors(values):
    key = values.get("type_key")
    if not key:
        return {KIND: "Pick an action."}
    if not values.get("target_user_id"):
        return {TARGET: "Pick a member."}
    if needs_expiry(key) and not values.get("expires_on"):
        return {UNTIL: f"A {label(key).lower()} needs an end date."}
    if needs_channel(key) and not values.get("channel_id"):
        return {WHERE: f"A {label(key).lower()} needs a channel."}
    if values.get("settle") == EXTEND and not values.get("expires_on"):
        return {UNTIL: "Pick the new end date."}
    if not values.get("reason"):
        return {REASON: "Add a reason."}
    return None


def details(values):
    if not takes_channel(values["type_key"]) or not values.get("channel_id"):
        return {}
    return {"channel_id": values["channel_id"]}
