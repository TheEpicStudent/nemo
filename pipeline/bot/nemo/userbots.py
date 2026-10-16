import logging

log = logging.getLogger("bot.nemo")

BOT_MESSAGE = "bot_message"

_users = {}


def fetch_user(client, user_id):
    try:
        return (client.users_info(user=user_id) or {}).get("user") or {}
    except Exception as failure:
        log.info("nemo: could not look up %s: %s", user_id, failure)
        return {}


def get_user(client, user_id):
    if user_id not in _users:
        user = fetch_user(client, user_id)
        if not user:
            return {}
        _users[user_id] = user
    return _users[user_id]


def is_person(client, user_id):
    return bool(user_id) and get_user(client, user_id).get("is_bot") is False


def posted_by_person(client, message):
    if not message.get("bot_id"):
        return True
    if message.get("subtype") == BOT_MESSAGE:
        return False
    return is_person(client, message.get("user"))
