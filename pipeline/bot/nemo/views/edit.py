from bot.core import richtext
from bot.nemo import categories as category_cache

MENU = "case_more"
MORE_ACTION = "case_more_pick"

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
BAN_LOG = "case_ban_log"

CATEGORY_FIELD = "category_what"
NOTE_BODY = "note_body"

NOTE_LIMIT = 5000
TITLE_LIMIT = 24
NO_LABEL = " "

def categories():
    return category_cache.active()


def option(text, value):
    return {"text": {"type": "plain_text", "text": text}, "value": value}


def choices(case):
    if case.get("resolved_at"):
        return [option("Reopen", REOPEN), option("Add note", NOTE), option("More…", MORE)]

    out = [] if case.get("assignees") else [option("Claim", CLAIM)]
    return out + [
        option("Log action", LOG_ACTION),
        option("Resolve", RESOLVE),
        option("Add note", NOTE),
        option("More…", MORE),
    ]


def menu(case):
    return {
        "type": "overflow",
        "action_id": MENU,
        "options": [
            option(choice["text"]["text"], f"{choice['value']}:{case['case_id']}")
            for choice in choices(case)
        ],
    }


def more_options(open_, category_key, live):
    options = [("People", PEOPLE)]
    if open_ and not category_key:
        options.append(("Set violation", CATEGORY))
    if live:
        options.append(("Reverse action", REVERSE))
    if open_:
        options.append(("Merge", MERGE))
    return options


def more_view(case_id, options, problem=None):
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
                "action_id": f"{MORE_ACTION}_{verb}",
                "text": {"type": "plain_text", "text": label},
                "value": f"{verb}:{case_id}",
            }
            for label, verb in options
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
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [{
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Cleared:* resolution, assignees",
            },
        }],
    }


def parse_menu_value(value):
    verb, _, case_id = (value or "").rpartition(":")
    return verb, int(case_id) if case_id.isdigit() else None


def category_view(case_id):
    return {
        "type": "modal",
        "callback_id": CATEGORY,
        "private_metadata": str(case_id),
        "title": {"type": "plain_text", "text": f"Violation · case {case_id}"[:TITLE_LIMIT]},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": CATEGORY_FIELD,
                "label": {"type": "plain_text", "text": NO_LABEL},
                "element": {
                    "type": "static_select",
                    "action_id": CATEGORY_FIELD,
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
        "submit": {"type": "plain_text", "text": "Save"},
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
                },
            }
        ],
    }


def selected_category(view_state):
    selected = view_state.get("values", {}).get(CATEGORY_FIELD, {}).get(CATEGORY_FIELD, {}).get("selected_option")
    return (selected or {}).get("value")


def submitted_values(view_state):
    values = view_state.get("values", {}).get(NOTE_BODY, {}).get(NOTE_BODY, {}).get("rich_text_value")
    return richtext.flatten(values)[:NOTE_LIMIT]


def note_errors(values):
    if not values:
        return {NOTE_BODY: "Enter a note"}
    return None


def category_label(key):
    return categories().get(key, (key or "").replace("_", " "))


def ban_prompt(case_id, target=None):
    return [{
        "type": "actions",
        "elements": [{
            "type": "button",
            "action_id": BAN_LOG,
            "text": {"type": "plain_text", "text": "Log action"},
            "style": "primary",
            "value": f"{case_id}:{target or ''}",
        }],
    }]


def parse_ban_value(value):
    case_id, _, target = (value or "").partition(":")
    return (int(case_id) if case_id.isdigit() else None), (target or None)
