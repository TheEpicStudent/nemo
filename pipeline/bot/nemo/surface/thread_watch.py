import logging

from bot.core import session
from bot.nemo import guards, guard_actions, userbots
from bot.nemo.enforcement import notify
from bot.nemo.surface import on_event
from bot.nemo.views import guard as card

log = logging.getLogger("bot.nemo")

HANDLED_SUBTYPES = (None, "file_share", "me_message", "thread_broadcast")


@on_event("message", open_to_all=True)
def watched(ctx):
    event = ctx.payload or {}
    if event.get("subtype") not in HANDLED_SUBTYPES:
        return None

    channel_id = event.get("channel")
    thread_ts = event.get("thread_ts")
    ts = event.get("ts")
    if not channel_id or not ts:
        return None
    if not thread_ts:
        if guards.watching(channel_id, ts):
            log.info("nemo: %s posted at the top of guarded thread %s", event.get("user"), ts)
        return None
    if not guards.watching(channel_id, thread_ts):
        return None
    if not userbots.posted_by_person(ctx.client, event):
        return None

    who = event.get("user")
    with session() as conn:
        guard = guards.active_guard(conn, channel_id, thread_ts)
        if guard is None:
            guards.refresh(conn)
            return None
        if guards.exempt(conn, who, guard[5]):
            log.info("nemo: guard %s let %s past, they are exempt", guard[0], who)
            return None
        noted = guard_actions.note_it(conn, guard, who, ts)

    if not noted:
        return None

    guard_actions.delete_notice(ctx.client, guard[0], channel_id, ts)
    if guard[1] == guards.LOCK:
        told = card.lock_held_back(guard[7], event.get("text") or "")
        notify.post_ephemeral(ctx.client, channel_id, who, told["text"], thread_ts=thread_ts,
                              blocks=told["blocks"])
    log.info("nemo: guard %s noted %s from %s", guard[0], ts, who)
    return guard_actions.threshold_met(guard, who) or "noted"
