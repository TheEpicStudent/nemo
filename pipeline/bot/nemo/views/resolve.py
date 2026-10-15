import yaml

from bot.core import richtext
from bot.core.formatting import short_end
from bot.nemo.views import action, lines
from lib.paths import RESOLUTIONS_FILE

CALLBACK = "case_resolve"

TITLE_LIMIT = 24

WHY = "resolve_why"
NOTE = "resolve_note"
NOTIFY = "resolve_notify"
MESSAGE = "resolve_message"

NOTIFY_REPORTER = "notify_reporter"

TABLE = None


def table():
    global TABLE
    if TABLE is None:
        TABLE = yaml.safe_load(RESOLUTIONS_FILE.read_text())
    return TABLE


def label(key):
    row = table()["resolutions"].get(key)
    return row["label"] if row else key.replace("_", " ")


def default_message():
    return table()["reporter_message"]


def reasons():
    submitted_values = {
        key: row
        for key, row in table()["resolutions"].items()
        if row.get("pick")
    }
    return sorted(submitted_values, key=lambda key: submitted_values[key]["pick"])


def forced(live_actions):
    return "action_taken" if live_actions else None


def until(at):
    return short_end(at) if at else None


def line(one):
    message = f"<@{one['target_user_id']}> - {action.label(one['type_key']).lower()}"
    where = (one.get("details") or {}).get("channel_id")
    if where:
        message += f" in <#{where}>"
    ends = until(one.get("expires_at"))
    if ends:
        message += f" until {ends}"
    return message


def live_actions_text(live_actions):
    return "\n".join(line(one) for one in live_actions)


def reason_input_block(live_actions):
    if forced(live_actions):
        return {"type": "section", "text": {"type": "mrkdwn", "text": live_actions_text(live_actions)}}

    return {
        "type": "input",
        "block_id": WHY,
        "label": {"type": "plain_text", "text": "Resolution"},
        "element": {
            "type": "static_select",
            "action_id": WHY,
            "options": [
                {"text": {"type": "plain_text", "text": label(key)}, "value": key}
                for key in reasons()
            ],
        },
    }


def build_view(case_id, live_actions=(), open_reports=0):
    blocks = [
        reason_input_block(live_actions),
        {
            "type": "input",
            "block_id": NOTE,
            "optional": True,
            "label": {"type": "plain_text", "text": "Note"},
            "element": {
                "type": "rich_text_input",
                "action_id": NOTE,
                "min_lines": 2,
                "placeholder": {
                    "type": "plain_text",
                    "text": "what happened",
                },
            },
        },
    ]

    if open_reports:
        blocks += [
            {
                "type": "input",
                "block_id": NOTIFY,
                "optional": True,
                "label": {"type": "plain_text", "text": "Reporter"},
                "element": {
                    "type": "checkboxes",
                    "action_id": NOTIFY,
                    "options": [
                        {
                            "text": {"type": "plain_text", "text": "Notify the reporter"},
                            "value": NOTIFY_REPORTER,
                        }
                    ],
                    "initial_options": [
                        {
                            "text": {"type": "plain_text", "text": "Notify the reporter"},
                            "value": NOTIFY_REPORTER,
                        }
                    ],
                },
            },
            {
                "type": "input",
                "block_id": MESSAGE,
                "optional": True,
                "label": {"type": "plain_text", "text": "Message to the reporter"},
                "element": {
                    "type": "plain_text_input",
                    "action_id": MESSAGE,
                    "multiline": True,
                    "initial_value": default_message(),
                },
            },
        ]

    return {
        "type": "modal",
        "callback_id": CALLBACK,
        "private_metadata": str(case_id),
        "title": {"type": "plain_text", "text": f"Resolve · case {case_id}"[:TITLE_LIMIT]},
        "submit": {"type": "plain_text", "text": "Resolve"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def submitted_values(view_state, live_actions=()):
    values = view_state.get("values", {})
    selected = (values.get(WHY, {}).get(WHY, {}).get("selected_option") or {}).get("value")
    checked_options = values.get(NOTIFY, {}).get(NOTIFY, {}).get("selected_options") or []
    message = values.get(MESSAGE, {}).get(MESSAGE, {}).get("value")

    note = richtext.flatten(values.get(NOTE, {}).get(NOTE, {}).get("rich_text_value"))

    return {
        "resolution": forced(live_actions) or selected,
        "member_note": note or None,
        "notify_reporter": any(one.get("value") == NOTIFY_REPORTER for one in checked_options),
        "message": (message or "").strip() or default_message(),
    }


def validation_errors(values):
    if not values.get("resolution"):
        return {WHY: "Pick a resolution."}
    if values.get("notify_reporter") and richtext.mentions(values.get("message")):
        return {MESSAGE: "Mentions cannot be sent to the reporter. Write the name instead."}
    return None


def by_line(resolution, by, case_id=None):
    resolution_label = None if resolution == "action_taken" else label(resolution)
    if case_id is None:
        return f"Resolved by <@{by}>" + (f" · {resolution_label}" if resolution_label else "")
    return lines.resolved(by, case_id, resolution_label)


def action_group_blocks(one):
    built = [{
        "type": "context",
        "elements": [{
            "type": "mrkdwn",
            "text": f"*{action.label(one['type_key'])}* against <@{one['target_user_id']}>",
        }],
    }]
    if one.get("reason"):
        built.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"> {one['reason']}"},
        })
    return built


def echo_blocks(resolution, member_note, by, actions=(), case_id=None):
    built = [{
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": by_line(resolution, by, case_id)}],
    }]

    if resolution == "action_taken":
        if actions:
            built.append({"type": "divider"})
            for one in actions:
                built.extend(action_group_blocks(one))
        if member_note:
            built.append({
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": f"*Outcome:* {member_note}",
                }],
            })
    elif member_note:
        built.append({"type": "divider"})
        built.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"> {member_note}"},
        })

    return built
