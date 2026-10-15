import logging

from bot.core import privileged
from bot.core.formatting import short_end
from bot.nemo import memberguards, userbots

log = logging.getLogger("bot.nemo")

SPAM = 10
WINDOW = "1 hour"

UNTIL = "until {when}"
ENDLESS = "with no end date"

HANDLED_SUBTYPES = (None, "file_share", "thread_broadcast", "me_message")


def ending(guard):
    at = guard.get("expires_at")
    return UNTIL.format(when=short_end(at)) if at else ENDLESS


def dm_subject(client, conn, guard, message):
    try:
        client.chat_postMessage(channel=guard["subject_id"], text=message)
        detail = None
    except Exception as failure:
        detail = f"could not notify them: {str(failure)[:200]}"
        log.warning("nemo: guard %s is held but %s was not notified: %s",
                    guard["id"], guard["subject_id"], failure)

    memberguards.record_enforcement(conn, guard["id"], guard["subject_id"], None,
                                   memberguards.NOTIFIED, detail=detail)


def post_ephemeral(client, channel_id, subject_id, message, thread_ts=None):
    try:
        client.chat_postEphemeral(channel=channel_id, user=subject_id, text=message,
                                   thread_ts=thread_ts)
    except Exception as failure:
        log.info("nemo: could not say why %s was stopped in %s: %s",
                 subject_id, channel_id, failure)


def reset_threshold_met(conn, guard, verb):
    if memberguards.lately(conn, guard["id"], verb, WINDOW) < SPAM:
        return False
    return memberguards.lately(conn, guard["id"], "reset", WINDOW) == 0


def reset(conn, guard, why):
    how = privileged.reset_sessions(guard["subject_id"], conn)
    memberguards.record_enforcement(conn, guard["id"], guard["subject_id"], None, "reset", detail=how)
    log.warning("nemo: %s kept %s through guard %s, sessions %s",
                guard["subject_id"], why, guard["id"], how)
    return how


def message_target(event, client):
    if event.get("subtype") not in HANDLED_SUBTYPES:
        return None, None, None

    channel_id = event.get("channel")
    subject_id = event.get("user")
    ts = event.get("ts")
    if not channel_id or not subject_id or not ts:
        return None, None, None
    if channel_id.startswith("D"):
        return None, None, None
    if not userbots.posted_by_person(client, event):
        return None, None, None
    return channel_id, subject_id, ts
