import logging

from bot.core import session
from bot.nemo import responses
from bot.nemo.surface import on_event

log = logging.getLogger("bot.nemo")


def plain(name):
    return (name or "").split("::")[0]


def is_a_person(client, user_id):
    try:
        user = (client.users_info(user=user_id) or {}).get("user") or {}
    except Exception as failure:
        log.info("nemo: could not look up %s: %s", user_id, failure)
        return False
    return not user.get("is_bot") and not user.get("deleted")


@on_event("reaction_added", open_to_all=True)
def reacted(ctx):
    event = ctx.payload or {}
    if (event.get("item") or {}).get("type") != "message":
        return None

    who = event.get("user")
    channel_id = (event.get("item") or {}).get("channel")
    if not who or not channel_id:
        return None
    if not responses.answering(channel_id, plain(event.get("reaction"))):
        return None

    with session() as conn:
        if not responses.may_answer(conn, who):
            return None

    if not is_a_person(ctx.client, who):
        return None

    try:
        ctx.client.chat_postMessage(channel=who, text=responses.setting(
            responses.AUTORESPONSE_BODY))
    except Exception as failure:
        log.warning("nemo: could not answer %s: %s", who, failure)
        return None

    log.info("nemo: answered %s about a conduct action", who)
    return who
