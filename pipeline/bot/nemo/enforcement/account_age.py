import logging

from bot.core import session
from bot.nemo import channelguards, guard_actions
from bot.nemo.enforcement import notify
from bot.nemo.surface import on_event

log = logging.getLogger("bot.nemo")

KIND = channelguards.ACCOUNT_AGE

DELETED = "deleted"

IN_CHANNEL = (
    "Your account must be {days} day{plural} old to post here. You can post in {left}."
    "\n\nYour message:\n{body}"
)

DAYS_REMAINING = """
SELECT ceil(extract(epoch FROM (known.at + make_interval(days => %s)) - now()) / 86400)::int
FROM (
    SELECT coalesce(j.joined_at, m.claimed_at) AS at
    FROM (SELECT %s::text AS user_id) asked
    LEFT JOIN fd.member_joins j ON j.user_id = asked.user_id
    LEFT JOIN analytics.dim_member m ON m.user_id = asked.user_id
) known
WHERE known.at IS NOT NULL
"""


def days_left(conn, user_id, days):
    row = conn.execute(DAYS_REMAINING, (days, user_id)).fetchone()
    if row is None:
        return None
    return row[0] if row[0] and row[0] > 0 else None


@on_event("message", open_to_all=True)
def on_message(ctx):
    event = ctx.payload or {}
    channel_id, subject_id, ts = notify.message_target(event, ctx.client)
    if not channel_id:
        return None

    guard = channelguards.guarding(channel_id, KIND)
    if guard is None or guard.lets_past(subject_id):
        return None

    days = guard.min_age_days()
    if days <= 0:
        return None

    with session() as conn:
        days_remaining = days_left(conn, subject_id, days)
    if days_remaining is None:
        return None

    body = event.get("text") or ""
    try:
        guard_actions.remove(ctx.client, channel_id, ts)
    except Exception as failure:
        log.warning("nemo: account age %s could not remove %s in %s: %s",
                    guard.guard_id, ts, channel_id, failure)
        return None

    with session() as conn:
        channelguards.record_enforcement(conn, guard.guard_id, channel_id, subject_id,
                               DELETED, text=body, message_ts=ts)

    notify.post_ephemeral(ctx.client, channel_id, subject_id, IN_CHANNEL.format(
        days=days, plural="" if days == 1 else "s",
        left=f"{days_remaining} day{'' if days_remaining == 1 else 's'}", body=body))
    log.info("nemo: account age %s removed %s from %s", guard.guard_id, ts, channel_id)
    return True
