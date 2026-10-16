from bot.nemo.views import action

CALLBACK = "case_action_reverse"

ACTION = "reverse_which"
REASON = "reverse_reason"

REASON_LIMIT = 500
TITLE_LIMIT = 24
NO_LABEL = " "


def label_of(one):
    end_suffix = f", until {one['expires_at']:%-d %b}" if one.get("expires_at") else ""
    return f"{action.label(one['type_key'])} on <@{one['target_user_id']}>{end_suffix}"


def option(one):
    return {
        "text": {"type": "plain_text", "text": label_of(one)[:75]},
        "value": str(one["id"]),
    }


def build_view(case_id, live):
    return {
        "type": "modal",
        "callback_id": CALLBACK,
        "private_metadata": str(case_id),
        "title": {"type": "plain_text", "text": f"Reverse · case {case_id}"[:TITLE_LIMIT]},
        "submit": {"type": "plain_text", "text": "Reverse"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "input",
                "block_id": ACTION,
                "label": {"type": "plain_text", "text": "Action"},
                "element": {
                    "type": "static_select",
                    "action_id": ACTION,
                    "placeholder": {"type": "plain_text", "text": "Select an action"},
                    "options": [option(one) for one in live],
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
                },
            },
        ],
    }


def submitted_values(state):
    values = state.get("values", {})
    selected_id = (values.get(ACTION, {}).get(ACTION, {}).get("selected_option") or {}).get("value")
    return {
        "action_id": int(selected_id) if selected_id else None,
        "reason": (values.get(REASON, {}).get(REASON, {}).get("value") or "").strip(),
    }


def validation_errors(values):
    if not values.get("action_id"):
        return {ACTION: "Select an action"}
    if not values.get("reason"):
        return {REASON: "Add a reason."}
    return None
