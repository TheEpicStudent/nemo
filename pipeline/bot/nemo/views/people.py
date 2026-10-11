CALLBACK = "case_people"
REMOVE = "case_people_remove"

WHO = "people_who"
ASSIGN = "people_assign"

TITLE_LIMIT = 24

SUBJECT = "subject"
ASSIGNEE = "assignee"

ROLE_LABEL = {"subject": "Subject", "reporter": "Reporter", ASSIGNEE: "Assigned"}


def label_of(user_id, role):
    return f"<@{user_id}> · {ROLE_LABEL.get(role, role)}"


def row(case_id, user_id, role, removable):
    made = {"type": "section", "text": {"type": "mrkdwn", "text": label_of(user_id, role)[:150]}}
    if removable:
        made["accessory"] = {
            "type": "button",
            "action_id": REMOVE,
            "text": {"type": "plain_text", "text": "Remove"},
            "style": "danger",
            "value": f"{user_id}:{role}:{case_id}",
        }
    return made


def picker(block_id, label, placeholder):
    return {
        "type": "input",
        "block_id": block_id,
        "optional": True,
        "label": {"type": "plain_text", "text": label},
        "element": {
            "type": "multi_users_select",
            "action_id": block_id,
            "placeholder": {"type": "plain_text", "text": placeholder},
        },
    }


def build_view(case_id, participants=(), assignees=(), can_people=True, can_assign=True):
    rows = [
        row(case_id, one["user_id"], one["role"], can_people) for one in participants
    ] + [row(case_id, user_id, ASSIGNEE, can_assign) for user_id in assignees]

    blocks = rows + ([{"type": "divider"}] if rows else [])
    if can_people:
        blocks.append(picker(WHO, "Subject", "who the case is about"))
    if can_assign:
        blocks.append(picker(ASSIGN, "Assign", "who to put on it"))

    view = {
        "type": "modal",
        "callback_id": CALLBACK,
        "private_metadata": str(case_id),
        "title": {"type": "plain_text", "text": f"People · case {case_id}"[:TITLE_LIMIT]},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks,
    }
    if can_people or can_assign:
        view["submit"] = {"type": "plain_text", "text": "Add"}
    return view


def chosen(values, block_id):
    return values.get(block_id, {}).get(block_id, {}).get("selected_users") or []


def submitted_values(state):
    values = state.get("values", {})
    return {"subjects": chosen(values, WHO), "assignees": chosen(values, ASSIGN)}


def removed(value):
    user_id, role, case_id = (value or "").split(":", 2)
    return user_id, role, int(case_id) if case_id.isdigit() else None


def validation_errors(values, shown):
    if values.get("subjects") or values.get("assignees"):
        return None
    first = WHO if WHO in shown else ASSIGN
    return {first: "Pick somebody first."}
