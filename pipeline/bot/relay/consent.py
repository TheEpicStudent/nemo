ANONYMOUS = "anonymous"
NAMED = "named"
ANONYMOUSLY = "anonymously"

BLOCK = "intake_identity"
ACTION = "intake_name"
CONFIRM = "intake_confirm"
CANCEL = "intake_cancel"

SUBTYPE = "consent"
DONE = "consent_done"

FALLBACK = "Submit this report to FD"


READY = (
    "Ready to send this report to FD with your username. Check the box below "
    "to send it anonymously."
)

IDENTITY_OPTION = {
    "text": {"type": "plain_text", "text": "Send it anonymously"},
    "description": {
        "type": "plain_text",
        "text": "FD will not see who filed this report. Leave unchecked to send it "
                "with your username.",
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
        summary_parts.append(f"↪️ {shared}")
    if files:
        plural = "s" if files != 1 else ""
        summary_parts.append(f"📎 {files} file{plural}")

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
                    "text": {"type": "plain_text", "text": "Submit"},
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


DROPPED = "Nothing was sent. Say more here whenever you want, and I will ask again."
ALREADY = "This one is already with the Fire Department."
