import datetime as dt
import logging

from bot.core import session
from bot.nemo import guards
from bot.nemo.views import guard as card
from bot.nemo.surface import on_shortcut, on_view

log = logging.getLogger("bot.nemo")

SHORTCUT = "lock_thread"


@on_shortcut(SHORTCUT, needs="thread.guard")
def open_lock_modal(ctx):
    if not ctx.thread_ts:
        return ctx.post_ephemeral("that is not a thread")

    ctx.client.views_open(
        trigger_id=ctx.trigger_id,
        view=card.lock_view(ctx.channel_id, ctx.thread_ts),
    )


@on_view(card.LOCK_CALLBACK, needs="thread.guard", refuse_block=card.REASON)
def confirmed(ctx):
    values = card.submitted_values(ctx.view.get("state") or {})
    errors = card.validation_errors(values, needs_until=True)
    if errors:
        return ctx.ack(response_action="errors", errors=errors)

    lock_until = dt.datetime.fromtimestamp(values["until"], dt.UTC)
    if lock_until <= dt.datetime.now(dt.UTC):
        return ctx.ack(response_action="errors", errors={card.UNTIL: "That is in the past."})

    ctx.ack()
    channel_id, thread_ts = card.opened(ctx.view)
    if not channel_id or not thread_ts:
        return None

    with session() as conn:
        guard_id = guards.open_guard(
            conn, guards.LOCK, channel_id, thread_ts, ctx.user_id, values["reason"],
            expires_at=lock_until,
        )

    if guard_id is None:
        return ctx.post_ephemeral("that thread is already held", channel_id, thread_ts)

    ctx.join(channel_id)
    with session() as conn:
        guards.warn(ctx.client, conn, guard_id, channel_id, thread_ts, guards.LOCK)
        guards.refresh(conn)

    log.info("nemo: %s locked %s until %s (guard %s)", ctx.user_id, thread_ts, lock_until, guard_id)
    return guard_id
