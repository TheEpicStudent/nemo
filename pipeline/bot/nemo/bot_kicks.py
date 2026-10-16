import logging
import threading

from bot.core import privileged, session, whoami
from bot.nemo import channelguards, userbots
from bot.nemo.surface import bot_watch

log = logging.getLogger("bot.nemo")

PER_PASS = 20
GIVE_UP_AFTER = 3

PENDING_KICKS = """
SELECT id, guard_id, channel_id, subject_id, attempts
FROM fd.bot_kicks
WHERE done_at IS NULL AND attempts < %s
ORDER BY queued_at
LIMIT %s
"""

MARK_DONE = "UPDATE fd.bot_kicks SET done_at = now(), outcome = %s, attempts = attempts + 1 WHERE id = %s"

RECORD_RETRY = "UPDATE fd.bot_kicks SET outcome = %s, attempts = attempts + 1 WHERE id = %s"

_lock = threading.Lock()


def bot_account(client, subject_id):
    if subject_id.startswith("B"):
        user_id, label, app_id = bot_watch.bot_info(client, subject_id)
        return user_id, label, app_id
    user = userbots.get_user(client, subject_id)
    if user.get("is_bot") is not True:
        return None, None, None
    profile = user.get("profile") or {}
    return subject_id, user.get("real_name") or profile.get("real_name"), profile.get("api_app_id")


def kick_bot(client, pending_kick):
    kick_id, guard_id, channel_id, subject_id, attempts = pending_kick
    user_id, label, app_id = bot_account(client, subject_id)
    if user_id is None:
        return kick_id, "not a bot"
    if user_id in bot_watch.exempt_bot_ids() | {whoami.bot_user_id(client, "nemo")}:
        return kick_id, "exempt"

    outcome = privileged.kick(channel_id, user_id)
    if outcome == "kicked":
        with session() as conn:
            channelguards.record_enforcement(conn, guard_id, channel_id, user_id, "kicked",
                                             bot_id=subject_id if subject_id.startswith("B") else None,
                                             label=label, app_id=app_id, notice_wanted=True)
    log.info("nemo: bot kick %s for %s in %s -> %s", kick_id, subject_id, channel_id, outcome)
    return kick_id, outcome


def drain(client):
    if not _lock.acquire(blocking=False):
        return 0
    try:
        with session() as conn:
            pending_kicks = conn.execute(PENDING_KICKS, (GIVE_UP_AFTER, PER_PASS)).fetchall()

        finished_count = 0
        for one in pending_kicks:
            kick_id, outcome = kick_bot(client, one)
            finished = not outcome.startswith("failed") or one[4] + 1 >= GIVE_UP_AFTER
            with session() as conn:
                conn.execute(MARK_DONE if finished else RECORD_RETRY, (outcome, kick_id))
            finished_count += finished
        return finished_count
    finally:
        _lock.release()
