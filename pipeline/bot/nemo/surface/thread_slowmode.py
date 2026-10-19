import datetime as dt
import logging

from bot.core import session
from bot.nemo import channelguards, channels, profile
from bot.nemo.surface import on_action, on_shortcut, on_view
from bot.nemo.views import slowmode as card

log = logging.getLogger("bot.nemo")

SHORTCUT = "slowmode_thread"

NOT_A_THREAD = "That message is not a thread."
ALREADY_ON = "Slow mode already enabled"
ALREADY_OFF = "Slow mode already ended"
NOT_POSTED = "Slow mode not enabled: Nemo could not post in this thread ({error_code})"
DISABLED = "Slow mode disabled"


@on_shortcut(SHORTCUT, needs="thread.guard")
def open_slowmode_modal(ctx):
    if not ctx.thread_ts:
        return ctx.post_ephemeral(NOT_A_THREAD)

    with session() as conn:
        current = channelguards.slowmode_row(conn, ctx.channel_id, ctx.thread_ts)
    tz = profile.timezone(ctx.client, ctx.user_id)
    ctx.client.views_open(
        trigger_id=ctx.trigger_id,
        view=card.build_view(ctx.channel_id, ctx.thread_ts, current, tz),
    )
    return None


def apply_slowmode(conn, channel_id, thread_ts, values, by, tz=dt.UTC):
    seconds = card.parse_seconds(values)
    current = channelguards.slowmode_row(conn, channel_id, thread_ts)
    if current is None and not values["starting"]:
        return None, None, ALREADY_OFF
    values["expires_at"] = card.new_end(values, tz, current)
    if current:
        guard_id = channelguards.update_slowmode(
            conn, current, seconds, by, values["reason"], values["expires_at"])
    else:
        guard_id = channelguards.open_slowmode(
            conn, channel_id, thread_ts, seconds, by, values["reason"], values["expires_at"])
    if guard_id is None:
        return None, current, ALREADY_OFF if current else ALREADY_ON
    channelguards.set_allows(conn, guard_id, values["exempt"], by)
    channelguards.refresh(conn)
    return guard_id, current, None


def post_notice(ctx, guard_id, channel_id, thread_ts, values):
    ctx.join(channel_id)
    try:
        sent = ctx.client.chat_postMessage(
            channel=channel_id, thread_ts=thread_ts, unfurl_links=False,
            **card.notice(card.parse_seconds(values), values["expires_at"]),
        )
    except Exception as failure:
        error_code = channels.slack_error_code(failure)
        with session() as conn:
            channelguards.lift(conn, guard_id, ctx.user_id)
            channelguards.refresh(conn)
        log.warning("nemo: thread slow mode %s lifted, notice not posted: %s", guard_id, error_code)
        ctx.post_ephemeral(NOT_POSTED.format(error_code=error_code), channel_id, thread_ts)
        return False
    with session() as conn:
        channelguards.set_notice_ts(conn, guard_id, (sent or {}).get("ts"))
    return True


@on_view(card.CALLBACK, needs="thread.guard", refuse_block=card.REASON)
def submit_slowmode(ctx):
    values = card.submitted_values(ctx.view.get("state") or {}, card.is_extending(ctx.view))
    channel_id, thread_ts = card.parse_metadata(ctx.view)
    tz = profile.timezone(ctx.client, ctx.user_id)
    errors = card.validation_errors(values, tz)
    if errors and card.END in errors:
        with session() as conn:
            current = channelguards.slowmode_row(conn, channel_id, thread_ts)
        return ctx.ack(response_action="update",
                       view=card.build_view(channel_id, thread_ts, current, tz, values, errors[card.END]))
    if errors:
        return ctx.ack(response_action="errors", errors=errors)

    ctx.ack()
    if not channel_id or not thread_ts:
        return None

    with session() as conn:
        guard_id, current, refusal = apply_slowmode(conn, channel_id, thread_ts, values, ctx.user_id, tz)

    if refusal:
        return ctx.post_ephemeral(refusal, channel_id, thread_ts)
    if current is None and not post_notice(ctx, guard_id, channel_id, thread_ts, values):
        return None

    verb = "updated" if current else "enabled"
    log.info("nemo: %s %s thread slow mode %s on %s", ctx.user_id, verb, guard_id, thread_ts)
    return guard_id


@on_action(card.DISABLE, needs="thread.guard")
def disable_slowmode(ctx):
    view = ctx.view
    if view.get("callback_id") != card.CALLBACK:
        return None

    channel_id, thread_ts = card.parse_metadata(view)
    with session() as conn:
        current = channelguards.slowmode_row(conn, channel_id, thread_ts)
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
