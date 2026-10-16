import logging
import threading

from bot.core import privileged, session
from bot.nemo import channel, guards, profile
from bot.nemo.views import guard as card

log = logging.getLogger("bot.nemo")

_running = set()
_lock = threading.Lock()


def claim(guard_id):
    with _lock:
        if guard_id in _running:
            return False
        _running.add(guard_id)
        return True


def release(guard_id):
    with _lock:
        _running.discard(guard_id)


def invite_admin(client, channel_id):
    who = privileged.admin_user_id()
    if not who:
        return False
    try:
        client.conversations_invite(channel=channel_id, users=who)
    except Exception as failure:
        if "already_in_channel" not in str(failure):
            log.warning("nemo: could not invite %s into %s: %s", who, channel_id, failure)
            return False
    log.info("nemo: invited %s into %s so the messages can be removed", who, channel_id)
    return True


def remove(client, channel_id, ts, max_retries=2):
    try:
        privileged.delete_message(channel_id, ts, max_retries=max_retries)
        return True
    except Exception as failure:
        if not privileged.channel_missing(failure):
            raise
        log.info("nemo: the admin account is not in %s, inviting it", channel_id)

    if not invite_admin(client, channel_id):
        raise RuntimeError(f"the admin account could not join {channel_id}")

    privileged.delete_message(channel_id, ts, max_retries=max_retries)
    return True


def archive_url(channel_id, thread_ts):
    return channel.app_url(f"/cdn/destroy/{channel_id}_{thread_ts}")


def post_destroy_notice(client, conn, channel_id, thread_ts, by, deleted=0):
    noun = "message" if deleted == 1 else "messages"
    notice = f"Thread destroyed · <#{channel_id}> · {deleted} {noun} · by <@{by}>"
    url = archive_url(channel_id, thread_ts)
    if url:
        notice += f" · <{url}|archive>"

    log_channel_id = channel.log_channel(conn)
    if not log_channel_id:
        log.warning("nemo: no nemo.log_channel to say that %s was destroyed", channel_id)
        return

    try:
        client.chat_postMessage(channel=log_channel_id, text=notice, unfurl_links=False)
    except Exception as failure:
        log.warning("nemo: could not say that %s was destroyed: %s", channel_id, failure)


def signature_block(by):
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"Fire Department \u00b7 <@{by}>"}],
    }


def post_note(client, guard_id, channel_id, thread_ts, by):
    with session() as conn:
        note_row = guards.note_for(conn, guard_id)
    if note_row is None:
        return None

    note, text, already = note_row
    if already:
        return already
    if not note:
        return None

    try:
        response = client.chat_postMessage(
            channel=channel_id, thread_ts=thread_ts, text=text,
            blocks=[note, signature_block(by)], unfurl_links=False,
        )
    except Exception as failure:
        log.warning("nemo: guard %s could not leave the note: %s", guard_id, failure)
        return None

    ts = (response or {}).get("ts")
    if ts:
        with session() as conn:
            guards.note_posted(conn, guard_id, ts)
    return ts


def unremoved_timestamps(messages, thread_ts, note_ts=None):
    excluded_ts = {thread_ts, note_ts} if note_ts else {thread_ts}
    stamps = [one["ts"] for one in messages if one.get("ts") and one["ts"] not in excluded_ts]
    return stamps or [thread_ts]


def user_names(client, messages):
    names = {}
    for one in messages:
        user_id = one.get("user")
        if not user_id or user_id in names:
            continue
        names[user_id] = profile.profile(client, user_id)["name"]
    return names


def run_destroy(client, guard_id):
    if not claim(guard_id):
        return 0
    try:
        return destroy(client, guard_id)
    finally:
        release(guard_id)


def destroy(client, guard_id):
    with session() as conn:
        guard = guards.by_id(conn, guard_id)
        if guard is None:
            return 0
        gid, kind, channel_id, thread_ts, state, by, _warned, _expires = guard
        if kind != guards.DESTROY or state not in ("warned", "running"):
            return 0
        guards.start(conn, gid)

    try:
        messages = guards.transcript(client, channel_id, thread_ts)
    except Exception as failure:
        log.warning("nemo: guard %s could not read the thread: %s", gid, failure)
        with session() as conn:
            guards.finish(conn, gid, "failed", f"could not read the thread: {failure}")
            guards.refresh(conn)
        return 0

    names = user_names(client, messages)
    with session() as conn:
        guards.store_transcript(conn, gid, channel_id, thread_ts, messages, names)
    log.info("nemo: guard %s kept %s message(s) before deleting", gid, len(messages))

    note_ts = post_note(client, gid, channel_id, thread_ts, by)

    deleted, failed = 0, None
    for _ in range(guards.MAX_PASSES):
        try:
            messages = guards.transcript(client, channel_id, thread_ts)
        except Exception as failure:
            if "thread_not_found" in str(failure):
                break
            failed = str(failure)[:200]
            break

        stamps = unremoved_timestamps(messages, thread_ts, note_ts)

        removed_count = 0
        for ts in stamps:
            try:
                remove(client, channel_id, ts)
                removed_count += 1
            except Exception as failure:
                log.warning("nemo: guard %s could not delete %s: %s", gid, ts, failure)

        deleted += removed_count
        with session() as conn:
            guards.add_progress(conn, gid, removed_count)

        if removed_count == 0:
            failed = "slack refused every delete in a pass"
            break
        if stamps == [thread_ts]:
            break

    with session() as conn:
        guards.finish(conn, gid, "failed" if failed else "done", failed, None)
        guards.refresh(conn)
        if not failed:
            post_destroy_notice(client, conn, channel_id, thread_ts, by, deleted)

    log.info("nemo: guard %s destroyed %s message(s)%s", gid, deleted,
             f", stopped on {failed}" if failed else "")
    return deleted


def lift_lock(client, guard_id, by=None):
    with session() as conn:
        guard = guards.by_id(conn, guard_id)
        if guard is None:
            return None
        gid, kind, channel_id, _thread_ts, state, _by, _warned, _expires = guard
        if kind != guards.LOCK or state not in ("warned", "running"):
            return None
        guards.finish(conn, gid, "done", by=by)
        guards.refresh(conn)

    log.info("nemo: guard %s lifted the lock on %s", gid, channel_id)
    remove_lock_warnings(client)
    return gid


WARNINGS_PER_PASS = 50


def remove_lock_warnings(client):
    with session() as conn:
        waiting = guards.warnings_to_remove(conn, WARNINGS_PER_PASS)

    removed_count = 0
    for guard_id, channel_id, thread_ts, warned_ts in waiting:
        try:
            client.chat_delete(channel=channel_id, ts=warned_ts)
        except Exception as failure:
            if not (privileged.already_deleted(failure) or privileged.channel_missing(failure)):
                log.warning("nemo: guard %s lock notice not removed yet: %s", guard_id, failure)
                continue
        try:
            client.reactions_remove(channel=channel_id, timestamp=thread_ts, name=guards.LOCK_REACTION)
        except Exception as failure:
            log.info("nemo: guard %s lock mark not removed from %s: %s", guard_id, thread_ts, failure)
        with session() as conn:
            guards.warning_removed(conn, guard_id)
        removed_count += 1
    return removed_count


def lock_notice(conn, expires_at, reason, by):
    return card.lock_notice(expires_at, reason, by, signs_out=privileged.mode(conn) == privileged.ON)


def update_lock_notice(client, guard_id):
    with session() as conn:
        row = guards.lock_notice_row(conn, guard_id)
        if row is None:
            return None
        notice = lock_notice(conn, row["expires_at"], row["reason"], row["opened_by"])
    try:
        client.chat_update(channel=row["channel_id"], ts=row["warned_ts"], **notice)
    except Exception as failure:
        log.warning("nemo: guard %s lock notice not updated: %s", guard_id, failure)
        return None
    return row["warned_ts"]


def after_guard_change(client, guard_id):
    run_destroy(client, guard_id)
    remove_lock_warnings(client)
    update_lock_notice(client, guard_id)


def record_guarded_message(conn, guard, user_id, ts):
    gid, _kind, channel_id, _thread_ts, _state, _by, warned_ts, _expires = guard

    if warned_ts is None or ts <= warned_ts:
        return False

    guards.record_message(conn, gid, channel_id, user_id, ts)
    return True


def delete_guarded_message(client, guard_id, channel_id, ts):
    try:
        remove(client, channel_id, ts)
    except Exception as failure:
        if not privileged.already_deleted(failure):
            log.warning("nemo: guard %s could not remove %s yet: %s", guard_id, ts, failure)
            return False
        log.info("nemo: guard %s found %s already gone", guard_id, ts)

    with session() as conn:
        guards.mark_message_removed(conn, guard_id, ts)
    return True


def record_and_escalate(guard, user_id):
    gid, _kind, channel_id, thread_ts, _state, _by, _warned, _expires = guard

    with session() as conn:
        count = guards.message_count(conn, gid, user_id)
        needed = privileged.strikes_needed(conn)
    if count < needed:
        return None

    outcome = escalate(gid, user_id, channel_id, thread_ts, count)
    if outcome:
        log.warning("nemo: guard %s -> sessions %s for %s after %s message(s)",
                    gid, outcome, user_id, count)
    return outcome


STILL_UP_PER_SWEEP = 200


def sweep_removals(client):
    with session() as conn:
        waiting = guards.unremoved_messages(conn, STILL_UP_PER_SWEEP)
    if not waiting:
        return 0

    removed_count = 0
    for guard_id, channel_id, ts in waiting:
        if delete_guarded_message(client, guard_id, channel_id, ts):
            removed_count += 1

    log.info("nemo: cleared %s of %s message(s) the guard could not remove first time",
             removed_count, len(waiting))
    return removed_count


def escalate(guard_id, user_id, channel_id, thread_ts, messages):
    if privileged.mode() == privileged.OFF:
        return None

    with session() as conn:
        cap = privileged.cap_per_guard(conn)
        if cap and guards.strike_count(conn, guard_id) >= cap:
            log.warning("nemo: guard %s hit the reset cap of %s, leaving %s alone",
                        guard_id, cap, user_id)
            return None
        if not guards.claim_reset(conn, guard_id, user_id, messages):
            return None

    outcome = privileged.reset_sessions(user_id)

    with session() as conn:
        guards.reset_done(conn, guard_id, user_id, outcome, channel_id, thread_ts, messages)
    return outcome


def sweep_strikes():
    needed = privileged.strikes_needed()
    with session() as conn:
        over = guards.users_over_threshold(conn, needed)

    escalated_count = 0
    for guard_id, user_id, messages, channel_id, thread_ts in over:
        if not claim(guard_id):
            continue
        try:
            outcome = escalate(guard_id, user_id, channel_id, thread_ts, messages)
        except Exception as failure:
            log.warning("nemo: guard %s could not escalate %s: %s", guard_id, user_id, failure)
            continue
        finally:
            release(guard_id)

        if outcome:
            escalated_count += 1
            log.warning("nemo: guard %s -> sessions %s for %s after %s message(s)",
                        guard_id, outcome, user_id, messages)
    return escalated_count
