import yaml

from bot.nemo.views import action, lines
from lib.paths import RESOLUTIONS_FILE

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


def log_blocks(resolution, member_note, by, actions=(), case_id=None):
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
                    "text": f"*Summary:* {member_note}",
                }],
            })
    elif member_note:
        built.append({"type": "divider"})
        built.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"> {member_note}"},
        })

    return built
