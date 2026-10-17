from bot.nemo import categories as category_cache

BAN_LOG = "case_ban_log"


def categories():
    return category_cache.active()


def option(text, value):
    return {"text": {"type": "plain_text", "text": text}, "value": value}


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
