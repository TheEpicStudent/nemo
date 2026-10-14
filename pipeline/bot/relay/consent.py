ANONYMOUS = "anonymous"
NAMED = "named"
ANONYMOUSLY = "anonymously"

BLOCK = "intake_identity"
ACTION = "intake_name"
CONFIRM = "intake_confirm"
CANCEL = "intake_cancel"

SUBTYPE = "consent"
DONE = "consent_done"

FALLBACK = "Send this report to the Fire Department?"


READY = (
    "This report goes to the Fire Department with your name. Tick the box to send it "
    "anonymously."
)

IDENTITY_OPTION = {
    "text": {"type": "plain_text", "text": "Send anonymously"},
    "description": {
        "type": "plain_text",
        "text": "The Fire Department will not see who sent it.",
    },
    "value": ANONYMOUSLY,
}


def forwarded(channels):
    if not channels:
        return None

    counted = f"{len(channels)} forwarded message" + ("s" if len(channels) != 1 else "")
    named = [f"#{one}" for one in channels if one]
    if not named:
        return counted

    where = ", ".join(dict.fromkeys(named))
    return f"{counted}, from {where}"


def build_blocks(bodies=None, files=0, channels=(), saved_choice=None):
    built = [{"type": "section", "text": {"type": "mrkdwn", "text": READY}}]

    summary_parts = []
    shared = forwarded(list(channels))
    if shared:
        summary_parts.append(shared)
    if files:
        plural = "s" if files != 1 else ""
        summary_parts.append(f"{files} file{plural}")

    if summary_parts:
        built.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "  ·  ".join(summary_parts)}],
            }
        )

    identity_checkbox = {
        "type": "checkboxes",
        "action_id": ACTION,
        "options": [IDENTITY_OPTION],
    }
    if saved_choice == ANONYMOUS:
        identity_checkbox["initial_options"] = [IDENTITY_OPTION]

    built += [
        {"type": "actions", "block_id": BLOCK, "elements": [identity_checkbox]},
        {
            "type": "actions",
            "block_id": "intake_send",
            "elements": [
                {
                    "type": "button",
                    "action_id": CONFIRM,
                    "style": "primary",
                    "text": {"type": "plain_text", "text": "Send"},
                },
                {
                    "type": "button",
                    "action_id": CANCEL,
                    "style": "danger",
                    "text": {"type": "plain_text", "text": "Cancel"},
                },
            ],
        },
    ]
    return built


def submitted_values(state):
    block_values = (state or {}).get("values", {}).get(BLOCK, {})
    if ACTION not in block_values:
        return None

    checked_options = block_values[ACTION].get("selected_options") or []
    return ANONYMOUS if any(one.get("value") == ANONYMOUSLY for one in checked_options) else NAMED


def resolve_choice(state, saved_choice=None):
    return submitted_values(state) or saved_choice or NAMED


DROPPED = "Cancelled, nothing was sent. Send a new message here to start a new report."
ALREADY = "This report was already sent."
