from bot.nemo.views import edit

CALLBACK = "case_merge"
KEEP = "merge_keep"
FOLD = "merge_fold"

OPTION_LIMIT = 100
TEXT_LIMIT = 75


def label(case_id, category_key, names):
    parts = [str(case_id), edit.category_label(category_key) if category_key else None, names]
    return " · ".join(part for part in parts if part)[:TEXT_LIMIT]


def option(one):
    case_id, category_key, names = one
    return {"text": {"type": "plain_text", "text": label(case_id, category_key, names)},
            "value": str(case_id)}


def build_view(cases, keep=None, fold=()):
    options = [option(one) for one in cases[:OPTION_LIMIT]]
    by_id = {one["value"]: one for one in options}

    keeping = {
        "type": "static_select",
        "action_id": KEEP,
        "placeholder": {"type": "plain_text", "text": "the case that stays open"},
        "options": options,
    }
    if str(keep) in by_id:
        keeping["initial_option"] = by_id[str(keep)]

    folding = {
        "type": "multi_static_select",
        "action_id": FOLD,
        "placeholder": {"type": "plain_text", "text": "cases to close into it"},
        "options": options,
    }
    picked = [by_id[str(one)] for one in fold if str(one) in by_id]
    if picked:
        folding["initial_options"] = picked

    return {
        "type": "modal",
        "callback_id": CALLBACK,
        "title": {"type": "plain_text", "text": "Merge cases"},
        "submit": {"type": "plain_text", "text": "Merge"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {"type": "input", "block_id": KEEP,
             "label": {"type": "plain_text", "text": "Keep open"}, "element": keeping},
            {"type": "input", "block_id": FOLD,
             "label": {"type": "plain_text", "text": "Close into it"}, "element": folding},
        ],
    }


def submitted_values(state):
    values = state.get("values", {})
    keep = (values.get(KEEP, {}).get(KEEP, {}).get("selected_option") or {}).get("value")
    fold = values.get(FOLD, {}).get(FOLD, {}).get("selected_options") or []
    return {
        "keep": int(keep) if keep else None,
        "fold": [int(one["value"]) for one in fold],
    }


def validation_errors(values):
    if not values.get("keep"):
        return {KEEP: "Pick the case that stays open."}
    if not values.get("fold"):
        return {FOLD: "Pick at least one case to close into it."}
    if values["keep"] in values["fold"]:
        return {FOLD: "The case you keep cannot close into itself."}
    return None


def asked(text):
    numbers = []
    for word in (text or "").replace(",", " ").split():
        word = word.lstrip("#")
        if word.isdigit():
            numbers.append(int(word))
    keep, *fold = numbers or [None]
    return keep, fold
