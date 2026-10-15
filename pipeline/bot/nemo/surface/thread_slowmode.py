import logging

from bot.core import session
from bot.nemo import channelguards, channels
from bot.nemo.surface import on_action, on_shortcut, on_view
from bot.nemo.views import slowmode as card

log = logging.getLogger("bot.nemo")

SHORTCUT = "slowmode_thread"

NOT_A_THREAD = "That message is not a thread."
ALREADY_ON = "Slow mode is already enabled in this thread."
ALREADY_OFF = "Slow mode was disabled before the change was saved."
NOT_POSTED = "Slow mode not enabled · Nemo could not post in this thread ({error_code})"
DISABLED = "Slow mode disabled"


@on_shortcut(SHORTCUT, needs="thread.guard")
def open_slowmode_modal(ctx):
    if not ctx.thread_ts:
        return ctx.post_ephemeral(NOT_A_THREAD)

    with session() as conn:
        current = channelguards.thread_slowmode_row(conn, ctx.channel_id, ctx.thread_ts)
    ctx.client.views_open(
        trigger_id=ctx.trigger_id,
        view=card.build_view(ctx.channel_id, ctx.thread_ts, current),
    )
    return None


def save(conn, channel_id, thread_ts, values, by):
    seconds = card.seconds_of(values)
    current = channelguards.thread_slowmode_row(conn, channel_id, thread_ts)
    if current:
        guard_id = channelguards.tune_thread_slowmode(
            conn, current, seconds, by, values["reason"], values["expires_at"])
    else:
        guard_id = channelguards.open_thread_slowmode(
            conn, channel_id, thread_ts, seconds, by, values["reason"], values["expires_at"])
    if guard_id is not None:
        channelguards.set_allows(conn, guard_id, values["exempt"], by)
        channelguards.refresh(conn)
    return guard_id, current


def post_notice(ctx, guard_id, channel_id, thread_ts, values):
    ctx.join(channel_id)
    try:
        ctx.client.chat_postMessage(
            channel=channel_id, thread_ts=thread_ts, unfurl_links=False,
            **card.notice(card.seconds_of(values), values["expires_at"], ctx.user_id),
        )
    except Exception as failure:
        error_code = channels.refusal(failure)
        with session() as conn:
            channelguards.lift(conn, guard_id, ctx.user_id)
            channelguards.refresh(conn)
        log.warning("nemo: thread slow mode %s lifted, notice not posted: %s", guard_id, error_code)
        ctx.post_ephemeral_or_dm(NOT_POSTED.format(error_code=error_code), channel_id, thread_ts)
        return False
    return True


@on_view(card.CALLBACK, needs="thread.guard", refuse_block=card.REASON)
def saved(ctx):
    values = card.submitted_values(ctx.view.get("state") or {})
    errors = card.validation_errors(values)
    if errors:
        return ctx.ack(response_action="errors", errors=errors)

    ctx.ack()
    channel_id, thread_ts = card.opened(ctx.view)
    if not channel_id or not thread_ts:
        return None

    with session() as conn:
        guard_id, current = save(conn, channel_id, thread_ts, values, ctx.user_id)

    if guard_id is None:
        return ctx.post_ephemeral(ALREADY_OFF if current else ALREADY_ON, channel_id, thread_ts)
    if current is None and not post_notice(ctx, guard_id, channel_id, thread_ts, values):
        return None

    verb = "updated" if current else "enabled"
    ctx.post_ephemeral(
        card.confirmation(verb, card.seconds_of(values), values["expires_at"], values["reason"]),
        channel_id, thread_ts,
    )
    log.info("nemo: %s %s thread slow mode %s on %s", ctx.user_id, verb, guard_id, thread_ts)
    return guard_id


@on_action(card.DISABLE, needs="thread.guard")
def disabled(ctx):
    view = ctx.view
    if view.get("callback_id") != card.CALLBACK:
        return None

    channel_id, thread_ts = card.opened(view)
    with session() as conn:
        current = channelguards.thread_slowmode_row(conn, channel_id, thread_ts)
        lifted = current is not None and channelguards.lift(conn, current["id"], ctx.user_id)
        channelguards.refresh(conn)

    try:
        ctx.client.views_update(view_id=view["id"], hash=view.get("hash"), view=card.disabled_view())
    except Exception as failure:
        log.warning("nemo: could not close the slow mode modal: %s", failure)

    if lifted:
        ctx.post_ephemeral(DISABLED, channel_id, thread_ts)
        log.info("nemo: %s disabled thread slow mode %s on %s", ctx.user_id, current["id"], thread_ts)
    return current["id"] if current else None
