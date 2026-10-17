import logging

from bot.core import privileged, session
from bot.nemo import channelguards, exemptions, guard_actions, guards
from bot.nemo.enforcement import notify
from bot.nemo.surface import on_event
from bot.nemo.views import slowmode as card

log = logging.getLogger("bot.nemo")

KIND = channelguards.SLOWMODE

DELETED = "deleted"

NOTICE_ATTEMPTS = 3
NOTICES_PER_PASS = 20

CLAIM_NOTICES = """
UPDATE fd.channel_guards
SET notice_wanted = false, notice_attempts = notice_attempts + 1
WHERE id IN (
    SELECT id FROM fd.channel_guards
    WHERE notice_wanted AND state = 'live'
    ORDER BY id
    LIMIT %s
    FOR UPDATE SKIP LOCKED
)
RETURNING id, channel_id, thread_ts, settings, expires_at, opened_by, notice_attempts
"""

NOTICE_POSTED = "UPDATE fd.channel_guards SET notice_ts = %s WHERE id = %s"

CLAIM_STALE_NOTICES = """
UPDATE fd.channel_guards
SET notice_stale = false
WHERE id IN (
    SELECT id FROM fd.channel_guards
    WHERE notice_stale AND notice_ts IS NOT NULL AND state = 'live'
    ORDER BY id
    LIMIT %s
    FOR UPDATE SKIP LOCKED
)
RETURNING id, channel_id, settings, expires_at, notice_ts
"""

CLAIM_ENDED_NOTICES = """
UPDATE fd.channel_guards
SET notice_removed_at = now()
WHERE id IN (
    SELECT id FROM fd.channel_guards
    WHERE kind = 'slowmode' AND state = 'lifted'
      AND notice_ts IS NOT NULL AND notice_removed_at IS NULL
    ORDER BY id
    LIMIT %s
    FOR UPDATE SKIP LOCKED
)
RETURNING id, channel_id, notice_ts
"""

RELEASE_ENDED_NOTICE = "UPDATE fd.channel_guards SET notice_removed_at = NULL WHERE id = %s"

NOTICE_AGAIN = "UPDATE fd.channel_guards SET notice_wanted = state = 'live' WHERE id = %s"

CLAIM_SLOT = """
INSERT INTO fd.slowmode_clock (channel_id, thread_ts, user_id, posted_at)
VALUES (%s, %s, %s, now())
ON CONFLICT (channel_id, thread_ts, user_id) DO UPDATE SET posted_at = now()
WHERE fd.slowmode_clock.posted_at <= now() - make_interval(secs => %s)
RETURNING posted_at
"""

SECONDS_REMAINING = """
SELECT ceil(extract(epoch FROM (posted_at + make_interval(secs => %s)) - now()))::int
FROM fd.slowmode_clock
WHERE channel_id = %s AND thread_ts = %s AND user_id = %s
"""


def clock_scope(guard, event):
    thread_ts = event.get("thread_ts")
    if not thread_ts:
        return ""
    return thread_ts if guard.threads() else None


def claim_post_slot(conn, channel_id, thread_ts, user_id, seconds):
    return conn.execute(CLAIM_SLOT, (channel_id, thread_ts, user_id, seconds)).fetchone()


def seconds_remaining_for(conn, channel_id, thread_ts, user_id, seconds):
    row = conn.execute(SECONDS_REMAINING, (seconds, channel_id, thread_ts, user_id)).fetchone()
    return max(1, row[0]) if row and row[0] else 1


def reply_thread_ts(event):
    thread_ts = event.get("thread_ts")
    return thread_ts if thread_ts and thread_ts != event.get("ts") else None


def applicable_guard(channel_id, event):
    thread_ts = reply_thread_ts(event)
    if thread_ts:
        if guards.has_live_guard(channel_id, thread_ts):
            return None, None
        own = channelguards.thread_slowmode(channel_id, thread_ts)
        if own is not None:
            return own, thread_ts

    guard = channelguards.active_guard(channel_id, KIND)
    if guard is None:
        return None, None
    return guard, clock_scope(guard, event)


@on_event("message", open_to_all=True)
def on_message(ctx):
    event = ctx.payload or {}
    channel_id, subject_id, ts = notify.message_target(event, ctx.client)
    if not channel_id:
        return None

    guard, thread_ts = applicable_guard(channel_id, event)
    if guard is None or thread_ts is None or guard.allows(subject_id):
        return None

    seconds = guard.seconds()
    if seconds <= 0:
        return None

    with session() as conn:
        if exemptions.is_exempt(conn, subject_id):
            return None
        if claim_post_slot(conn, channel_id, thread_ts, subject_id, seconds):
            return None
        seconds_remaining = seconds_remaining_for(conn, channel_id, thread_ts, subject_id, seconds)

    body = event.get("text") or ""
    try:
        guard_actions.remove(ctx.client, channel_id, ts)
    except Exception as failure:
        log.warning("nemo: slow mode %s could not remove %s in %s: %s",
                    guard.guard_id, ts, channel_id, failure)
        return None

    with session() as conn:
        channelguards.record_enforcement(conn, guard.guard_id, channel_id, subject_id,
                               DELETED, text=body, message_ts=ts)

    notice = card.removal_notice(seconds_remaining, body, in_thread=bool(event.get("thread_ts")))
    notify.post_ephemeral(ctx.client, channel_id, subject_id, notice["text"],
                          thread_ts=event.get("thread_ts"), blocks=notice["blocks"])
    log.info("nemo: slow mode %s removed %s from %s", guard.guard_id, ts, channel_id)
    return True


def post_notices(client):
    with session() as conn:
        claimed = conn.execute(CLAIM_NOTICES, (NOTICES_PER_PASS,)).fetchall()

    posted = 0
    for guard_id, channel_id, thread_ts, settings, expires_at, _opened_by, attempts in claimed:
        seconds = int((settings or {}).get("seconds") or 0)
        try:
            sent = client.chat_postMessage(channel=channel_id, thread_ts=thread_ts or None,
                                           unfurl_links=False,
                                           **card.notice(seconds, expires_at))
        except Exception as failure:
            log.warning("nemo: slow mode %s notice not posted in %s (try %s): %s",
                        guard_id, channel_id, attempts, failure)
            if attempts < NOTICE_ATTEMPTS:
                with session() as conn:
                    conn.execute(NOTICE_AGAIN, (guard_id,))
            continue

        with session() as conn:
            conn.execute(NOTICE_POSTED, ((sent or {}).get("ts"), guard_id))
        posted += 1
    return posted


def refresh_notices(client):
    with session() as conn:
        claimed = conn.execute(CLAIM_STALE_NOTICES, (NOTICES_PER_PASS,)).fetchall()

    refreshed = 0
    for guard_id, channel_id, settings, expires_at, notice_ts in claimed:
        seconds = int((settings or {}).get("seconds") or 0)
        try:
            client.chat_update(channel=channel_id, ts=notice_ts, **card.notice(seconds, expires_at))
        except Exception as failure:
            log.warning("nemo: slow mode %s notice not updated in %s: %s", guard_id, channel_id, failure)
            continue
        refreshed += 1
    return refreshed


def remove_ended_notices(client):
    with session() as conn:
        claimed = conn.execute(CLAIM_ENDED_NOTICES, (NOTICES_PER_PASS,)).fetchall()

    removed = 0
    for guard_id, channel_id, notice_ts in claimed:
        try:
            client.chat_delete(channel=channel_id, ts=notice_ts)
        except Exception as failure:
            if guard_actions.CANT_DELETE in str(failure):
                guard_actions.delete_with_admin(guard_id, channel_id, notice_ts)
            elif not (privileged.already_deleted(failure) or privileged.channel_missing(failure)):
                log.warning("nemo: slow mode %s notice not removed yet: %s", guard_id, failure)
                with session() as conn:
                    conn.execute(RELEASE_ENDED_NOTICE, (guard_id,))
                continue
        removed += 1
    return removed


def sync_notices(client):
    return post_notices(client) + refresh_notices(client) + remove_ended_notices(client)
