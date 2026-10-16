import logging

from bot.core import session
from bot.nemo import automod, userbots
from bot.nemo.surface import on_event

log = logging.getLogger("bot.nemo")

HANDLED_SUBTYPES = (None, "file_share", "me_message", "thread_broadcast")
EDITED = "message_changed"


def permalink_for(client, channel_id, ts):
    try:
        return (client.chat_getPermalink(channel=channel_id, message_ts=ts) or {}).get("permalink")
    except Exception as failure:
        log.info("nemo: no permalink for %s in %s: %s", ts, channel_id, failure)
        return None


def posted_message(event):
    if event.get("subtype") not in HANDLED_SUBTYPES:
        return None
    return event


def edited_message(event):
    message = event.get("message") or {}
    if message.get("subtype") not in HANDLED_SUBTYPES:
        return None
    return {
        "bot_id": message.get("bot_id"),
        "user": message.get("user"),
        "channel": event.get("channel"),
        "ts": message.get("ts"),
        "thread_ts": message.get("thread_ts"),
        "text": message.get("text"),
    }


def message_from_event(event):
    message = edited_message(event) if event.get("subtype") == EDITED else posted_message(event)
    if not message:
        return None
    if not message.get("user") or not message.get("channel") or not message.get("ts"):
        return None
    return message


@on_event("message", open_to_all=True)
def match_automod_rules(ctx):
    message = message_from_event(ctx.payload or {})
    if not message:
        return None

    rules = automod.matching_rules(message.get("text"))
    if not rules:
        return None
    if not userbots.posted_by_person(ctx.client, message):
        return None

    with session() as conn:
        hit_ids = [row[0] for row in
                (automod.record(conn, rule, message) for rule in rules) if row]
        if not hit_ids:
            return None
        automod.link(conn, hit_ids, permalink_for(ctx.client, message["channel"], message["ts"]))

    log.info("nemo: automod caught %s word(s) in %s from %s",
             len(hit_ids), message["ts"], message.get("user"))
    return len(hit_ids)
