import datetime as dt
import logging
import time

from slack_sdk.errors import SlackApiError

from bot.core import audit, session
from bot.nemo import activity, channel
from bot.nemo.views import activity as card
from bot.nemo.surface import on_action, on_shortcut

log = logging.getLogger("bot.nemo")

SHORTCUT = "message_activity"

NOT_A_POST = "Activity is only available for top-level messages."
NOT_ENABLED = "Activity is not available in this channel."
NOT_YOURS = "You can only see activity for your own messages."
NOT_NOW = "Could not load activity. Try again in a minute."

FILE_NOT_READY = "slack_file"
FILE_RETRY_DELAY_SECONDS = 0.8
FILE_MAX_ATTEMPTS = 3


def update_view_with_chart(client, view_id, chart_view, fallback_view):
    """Poll until the uploaded file is usable in a block; render without the
    chart on timeout."""
    for attempt in range(FILE_MAX_ATTEMPTS):
        last = attempt == FILE_MAX_ATTEMPTS - 1
        try:
            return client.views_update(view_id=view_id, view=fallback_view if last else chart_view)
        except SlackApiError as failure:
            if FILE_NOT_READY not in str(failure):
                raise
            log.warning("activity: slack would not take the chart yet: %s", failure)
            time.sleep(FILE_RETRY_DELAY_SECONDS)
    return None


def is_reply(message):
    root = message.get("thread_ts")
    return bool(root) and root != message.get("ts")


def refused(conn, ctx, why, ts):
    audit.record(
        conn, "permission", 0, "refused", ctx.user_id,
        after={"permission": "message.read", "surface": f"shortcut:{SHORTCUT}",
               "channel_id": ctx.channel_id, "ts": ts},
    )
    return ctx.post_ephemeral(why)


@on_shortcut(SHORTCUT, needs="message.read")
def open_activity_modal(ctx):
    message = ctx.body.get("message") or {}
    ts = message.get("ts")
    if not ts or not ctx.channel_id:
        return ctx.post_ephemeral("That is not a message.")
    if is_reply(message):
        return ctx.post_ephemeral(NOT_A_POST)

    author_id = message.get("user")
    with session() as conn:
        if not activity.activity_enabled(conn, ctx.channel_id):
            return ctx.post_ephemeral(NOT_ENABLED)
        if not activity.may_read(ctx.user_id, author_id):
            return refused(conn, ctx, NOT_YOURS, ts)
        archived_message = activity.archived_message(conn, ctx.channel_id, ts)
        channel_members = activity.members(conn, ctx.channel_id)

    opened = ctx.client.views_open(trigger_id=ctx.trigger_id, view=card.loading_view())
    view_id = ((opened or {}).get("view") or {}).get("id")

    stats = activity.fetch(ctx.channel_id, ts)
    if stats is None:
        chart_view = fallback_view = card.error_view(NOT_NOW)
    else:
        posted_at = (archived_message or {}).get("posted_at") or dt.datetime.fromtimestamp(float(ts), dt.UTC)
        file_id, span = activity.chart(ctx.client, stats["curves"], posted_at, stats["viewers"])
        args = (ctx.channel_id, ts, author_id, message.get("text"), stats)
        view_kwargs = {"archived_message": archived_message, "channel_members": channel_members,
                "activity_url": channel.app_url(f"/messages/{ctx.channel_id}/{ts}")}
        chart_view = card.build_view(*args, chart=(file_id, span) if file_id else None, **view_kwargs)
        fallback_view = card.build_view(*args, **view_kwargs)

    if view_id:
        update_view_with_chart(ctx.client, view_id, chart_view, fallback_view)
    log.info("nemo: %s read how %s/%s did", ctx.user_id, ctx.channel_id, ts)
    return stats


@on_action(card.OPEN_ACTIVITY, open_to_all=True)
def on_open_activity(ctx):
    return None


@on_action(card.OPEN_TOP_REPLY, open_to_all=True)
def on_open_top_reply(ctx):
    return None
