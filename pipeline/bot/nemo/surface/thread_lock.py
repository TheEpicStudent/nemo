import datetime as dt
import logging

from bot.core import session
from bot.nemo import channels, guards
from bot.nemo.views import guard as card
from bot.nemo.surface import on_shortcut, on_view

log = logging.getLogger("bot.nemo")

SHORTCUT = "lock_thread"

WARNING_NOT_POSTED = (
    "Not locked: Nemo could not post in this thread ({error_code}). "
    "Run /invite @nemo in the channel, then lock the thread again."
)


@on_shortcut(SHORTCUT, needs="thread.guard")
def open_lock_modal(ctx):
    if not ctx.thread_ts:
        return ctx.post_ephemeral("That message is not a thread.")

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
        return ctx.ack(response_action="errors", errors={card.UNTIL: "Pick a date in the future."})

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
        return ctx.post_ephemeral("That thread is already locked or being destroyed.", channel_id, thread_ts)

    ctx.join(channel_id)
    error_code = None
    with session() as conn:
        try:
            guards.warn(ctx.client, conn, guard_id, channel_id, thread_ts, guards.LOCK)
        except Exception as failure:
            error_code = channels.refusal(failure)
            guards.finish(conn, guard_id, "failed", f"warning not posted: {error_code}")
        guards.refresh(conn)

    if error_code:
        log.warning("nemo: lock guard %s failed, warning not posted: %s", guard_id, error_code)
        ctx.post_ephemeral_or_dm(WARNING_NOT_POSTED.format(error_code=error_code), channel_id, thread_ts)
        return None

    log.info("nemo: %s locked %s until %s (guard %s)", ctx.user_id, thread_ts, lock_until, guard_id)
    return guard_id
