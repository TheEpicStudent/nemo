import logging

from bot.core import session
from bot.nemo import responses
from bot.nemo.surface import on_event

log = logging.getLogger("bot.nemo")


def plain(name):
    return (name or "").split("::")[0]


def is_human_user(client, user_id):
    try:
        user = (client.users_info(user=user_id) or {}).get("user") or {}
    except Exception as failure:
        log.info("nemo: could not look up %s: %s", user_id, failure)
        return False
    return not user.get("is_bot") and not user.get("deleted")


@on_event("reaction_added", open_to_all=True)
def send_autoresponse(ctx):
    event = ctx.payload or {}
    if (event.get("item") or {}).get("type") != "message":
        return None

    who = event.get("user")
    channel_id = (event.get("item") or {}).get("channel")
    if not who or not channel_id:
        return None
    if not responses.applies_to(channel_id, plain(event.get("reaction"))):
        return None

    with session() as conn:
        if not responses.claim_cooldown(conn, who):
            return None

    if not is_human_user(ctx.client, who):
        return None

    try:
        ctx.client.chat_postMessage(channel=who, text=responses.render_body(who))
    except Exception as failure:
        log.warning("nemo: could not answer %s: %s", who, failure)
        return None

    log.info("nemo: answered %s about a conduct action", who)
    return who
