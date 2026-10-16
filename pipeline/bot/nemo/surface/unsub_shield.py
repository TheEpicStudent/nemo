import logging

from bot.nemo import guard_actions, responses
from bot.nemo.enforcement import notify
from bot.nemo.surface import on_event

log = logging.getLogger("bot.nemo")

KEYWORD = "UNSUBSCRIBE"

NOTICE = (
    "To stop notifications from a thread, use *Turn off notifications for replies* on it."
)

WITH_LINK = "{text} <{link}|See how>"


def is_unsubscribe_request(event):
    return (event.get("text") or "").strip().upper() == KEYWORD


@on_event("message", open_to_all=True)
def on_message(ctx):
    event = ctx.payload or {}
    if not responses.unsub_shield_enabled():
        return None

    channel_id, subject_id, ts = notify.message_target(event, ctx.client)
    if not channel_id or not event.get("thread_ts") or not is_unsubscribe_request(event):
        return None

    try:
        guard_actions.remove(ctx.client, channel_id, ts)
    except Exception as failure:
        log.info("nemo: could not take down the unsubscribe in %s: %s", channel_id, failure)
        return None

    link = responses.setting(responses.UNSUB_SHIELD_LINK)
    notify.post_ephemeral(ctx.client, channel_id, subject_id,
                     WITH_LINK.format(text=NOTICE, link=link) if link else NOTICE)
    log.info("nemo: took down an unsubscribe from %s in %s", subject_id, channel_id)
    return True
