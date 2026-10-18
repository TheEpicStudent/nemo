import logging

from bot.core import session
from bot.nemo import channelguards, exemptions, guard_actions
from bot.nemo.enforcement import notify
from bot.nemo.surface import on_event
from bot.nemo.views import removal

log = logging.getLogger("bot.nemo")

KIND = channelguards.READONLY

DELETED = "deleted"

IN_CHANNEL = "This channel is read-only. Reply in a thread instead."


def in_a_thread(event):
    thread_ts = event.get("thread_ts")
    return bool(thread_ts) and event.get("subtype") != "thread_broadcast"


@on_event("message", open_to_all=True)
def on_message(ctx):
    event = ctx.payload or {}
    channel_id, subject_id, ts = notify.message_target(event, ctx.client)
    if not channel_id:
        return None

    guard = channelguards.active_guard(channel_id, KIND)
    if guard is None or guard.allows(subject_id):
        return None
    if in_a_thread(event) and not guard.threads():
        return None
    with session() as conn:
        if exemptions.is_exempt(conn, subject_id):
            return None

    body = event.get("text") or ""
    try:
        guard_actions.remove(ctx.client, channel_id, ts)
    except Exception as failure:
        log.warning("nemo: read-only %s could not remove %s in %s: %s",
                    guard.guard_id, ts, channel_id, failure)
        return None

    with session() as conn:
        channelguards.record_enforcement(conn, guard.guard_id, channel_id, subject_id,
                               DELETED, text=body, message_ts=ts)

    notice = removal.notice(IN_CHANNEL, body)
    notify.post_ephemeral(ctx.client, channel_id, subject_id, notice["text"],
                          thread_ts=event.get("thread_ts"), blocks=notice["blocks"])
    log.info("nemo: read-only %s removed %s from %s", guard.guard_id, ts, channel_id)
    return True
