import yaml

from bot.core import richtext
from lib.paths import CATEGORIES_FILE

MENU = "case_more"
MORE_PICK = "case_more_pick"

CLAIM = "case_claim"
LOG_ACTION = "case_log_action"
RESOLVE = "case_resolve_open"
REOPEN = "case_reopen"
REOPEN_CONFIRMED = "case_reopen_confirmed"
MORE = "case_more_open"
MERGE = "case_merge_open"
PEOPLE = "case_people"
ASSIGNEES = "case_assignees_open"
CATEGORY = "case_category"
NOTE = "case_note"
REVERSE = "case_reverse"

PROBLEM = "more_problem"

WHAT = "category_what"
NOTE_BODY = "note_body"

NOTE_LIMIT = 5000
TITLE_LIMIT = 24
NO_LABEL = " "

LABELS = None


def categories():
    global LABELS
    if LABELS is None:
        LABELS = yaml.safe_load(CATEGORIES_FILE.read_text())["categories"]
    return LABELS


def option(text, value):
    return {"text": {"type": "plain_text", "text": text}, "value": value}


def choices(case):
    if case.get("resolved_at"):
        return [option("Reopen", REOPEN), option("Leave a note", NOTE), option("More…", MORE)]

    out = [] if case.get("assignees") else [option("Claim it", CLAIM)]
    return out + [
        option("Log an action", LOG_ACTION),
        option("Resolve", RESOLVE),
        option("Leave a note", NOTE),
        option("More…", MORE),
    ]


def menu(case):
    return {
        "type": "overflow",
        "action_id": MENU,
        "options": [
            option(pick["text"]["text"], f"{pick['value']}:{case['case_id']}")
            for pick in choices(case)
        ],
    }


def more_picks(open_, category_key, live):
    picks = [("People", PEOPLE)]
    if open_ and not category_key:
        picks.append(("Set the violation", CATEGORY))
    if live:
        picks.append(("Reverse an action", REVERSE))
    if open_:
        picks.append(("Merge", MERGE))
    return picks


def more_view(case_id, picks, problem=None):
    blocks = []
    if problem:
        blocks.append({
            "type": "context",
            "block_id": PROBLEM,
            "elements": [{"type": "mrkdwn", "text": problem}],
        })
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "action_id": f"{MORE_PICK}_{verb}",
                "text": {"type": "plain_text", "text": label},
                "value": f"{verb}:{case_id}",
            }
            for label, verb in picks
        ],
    })
    return {
        "type": "modal",
        "private_metadata": str(case_id),
        "title": {"type": "plain_text", "text": f"Case {case_id}"[:TITLE_LIMIT]},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks,
    }


def notice_view(case_id, text):
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": f"Case {case_id}"[:TITLE_LIMIT]},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }


def reopen_view(case_id):
    return {
        "type": "modal",
        "callback_id": REOPEN_CONFIRMED,
        "private_metadata": str(case_id),
        "title": {"type": "plain_text", "text": f"Reopen case {case_id}"[:TITLE_LIMIT]},
        "submit": {"type": "plain_text", "text": "Reopen"},
        "close": {"type": "plain_text", "text": "Leave it closed"},
        "blocks": [{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "This drops the resolution and takes everybody off it. "
                "The case comes back unclaimed.",
            },
        }],
    }


def asked(value):
    verb, _, case_id = (value or "").rpartition(":")
    return verb, int(case_id) if case_id.isdigit() else None


def category_view(case_id):
    return {
        "type": "modal",
        "callback_id": CATEGORY,
        "private_metadata": str(case_id),
        "title": {"type": "plain_text", "text": f"Violation · case {case_id}"[:TITLE_LIMIT]},
        "submit": {"type": "plain_text", "text": "Set it"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": WHAT,
                "label": {"type": "plain_text", "text": NO_LABEL},
                "element": {
                    "type": "static_select",
                    "action_id": WHAT,
                    "options": [
                        option(label, key) for key, label in categories().items()
                    ],
                },
            },
        ],
    }


def note_view(case_id):
    return {
        "type": "modal",
        "callback_id": NOTE,
        "private_metadata": str(case_id),
        "title": {"type": "plain_text", "text": f"Note · case {case_id}"[:TITLE_LIMIT]},
        "submit": {"type": "plain_text", "text": "Keep it"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": NOTE_BODY,
                "label": {"type": "plain_text", "text": NO_LABEL},
                "element": {
                    "type": "rich_text_input",
                    "action_id": NOTE_BODY,
                    "min_lines": 3,
                    "placeholder": {
                        "type": "plain_text",
                        "text": "what you found, what you did",
                    },
                },
            }
        ],
    }


def what_picked(view_state):
    chosen = view_state.get("values", {}).get(WHAT, {}).get(WHAT, {}).get("selected_option")
    return (chosen or {}).get("value")


def submitted_values(view_state):
    values = view_state.get("values", {}).get(NOTE_BODY, {}).get(NOTE_BODY, {}).get("rich_text_value")
    return richtext.flatten(values)[:NOTE_LIMIT]


def note_objection(values):
    if not values:
        return {NOTE_BODY: "Write something first."}
    return None


def category_label(key):
    return categories().get(key, (key or "").replace("_", " "))
