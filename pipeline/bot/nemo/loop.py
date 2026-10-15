import logging
import os
import threading

from bot.core import loops, session
from bot.nemo import automod, channel, channelguards, channels, chat, guards, guard_actions
from bot.nemo import enforcement, guard_notices, guard_removals, memberguards, case_queue
from bot.nemo import join_requests, responses, screening
from bot.nemo.enforcement import purge, slowmode, sweep

log = logging.getLogger("bot.nemo")

NAME = "nemo"
CASES = "fd_case_changed"
CHAT = "fd_chat_changed"
OUTBOX = "fd_outbox_waiting"
CONVERSATION = "fd_conversation_changed"
GUARD = "fd_thread_guard"
CHANNEL_GUARD = "fd_channel_guard"
MEMBER_GUARD = "fd_member_guard"
APP_SETTING = "fd_app_setting"
AUTOMOD_WORD = "fd_automod_word"
PURGE = "fd_purge"
BLOCKED_DOMAIN = "fd_blocked_domain"
GUARD_NOTICE = "fd_guard_notice"
GUARD_REMOVE = "fd_guard_remove"
JOIN_REQUEST = "fd_channel_join_request"

DEFAULT_SECONDS = 300
DEFAULT_JOIN_SECONDS = 1800
GIVE_UP_AFTER = 3

UNCARDED = """
SELECT r.case_id
FROM fd.case_reports r
JOIN fd.intake_conversations v ON v.report_id = r.id
WHERE r.forwarded_ts IS NULL AND v.handed_off_at IS NOT NULL
ORDER BY r.received_at
LIMIT 20
"""

CARDLESS = """
SELECT c.id
FROM fd.cases c
WHERE c.card_ts IS NULL
  AND c.opened_at > now() - interval '1 day'
  AND NOT EXISTS (SELECT 1 FROM fd.case_reports r WHERE r.case_id = c.id)
ORDER BY c.opened_at
LIMIT 20
"""

WORTH_REDRAWING = """
SELECT r.case_id
FROM fd.case_reports r
JOIN fd.cases c ON c.id = r.case_id
WHERE r.forwarded_ts IS NOT NULL
  AND (c.resolved_at IS NULL OR c.resolved_at > now() - interval '2 days')
ORDER BY c.updated_at DESC
LIMIT 200
"""


def every():
    return int(os.environ.get("NEMO_SWEEP_SECONDS", DEFAULT_SECONDS))


def every_join_sweep():
    return int(os.environ.get("NEMO_JOIN_SECONDS", DEFAULT_JOIN_SECONDS))


def join_sweep(case_channel, stopping=None):
    client = case_channel.client
    apart(("joining configured channels", lambda: channels.join_configured(client)),
          ("joining channels", lambda: channels.reconcile(client, stopping=stopping)))


def join_configured(client):
    apart(("joining configured channels", lambda: channels.join_configured(client)))


def start_configured_joins(client):
    threading.Thread(target=join_configured, args=(client,), name="nemo-configured-joins",
                     daemon=True).start()


def join_channel(client, channel_id):
    if not channelguards.is_guarded(channel_id):
        return False

    with session() as conn:
        if channels.mode(conn) == channels.OFF or channels.inside(conn, channel_id):
            return False
        return channels.join(client, conn, channel_id, verb="joined")


def seat_and_announce(client, channel_id):
    apart((f"joining {channel_id}", lambda: join_channel(client, channel_id)),
          ("posting slow mode notices", lambda: slowmode.post_notices(client)))


def take_up(client, guard):
    with session() as conn:
        enforcement.take_up(client, conn, guard)


def apart(*doing):
    for name, work in doing:
        try:
            work()
        except Exception:
            log.exception("nemo: %s failed", name)


def start_purge(client, purge_id):
    threading.Thread(target=purge.run, args=(client, purge_id),
                     name=f"nemo-purge-{purge_id}", daemon=True).start()


def start_join_request(client, request_id):
    threading.Thread(target=join_requests.run, args=(client, int(request_id)),
                     name=f"nemo-join-request-{request_id}", daemon=True).start()


def lift_expired_locks(client):
    with session() as conn:
        due = guards.lifting(conn)
    for guard_id in due:
        apart((f"lifting guard {guard_id}", lambda one=guard_id: guard_actions.lift_lock(client, one)))


def lift_lapsed_channel_guards():
    with session() as conn:
        lifted = channelguards.lift_lapsed(conn)
        if lifted:
            channelguards.refresh(conn)
    for guard_id, kind, channel_id, thread_ts in lifted:
        log.info("nemo: %s guard %s on %s%s ended", kind, guard_id, channel_id,
                 f" thread {thread_ts}" if thread_ts else "")
    return len(lifted)


def lift_due(client):
    apart(("lifting what has run out", lambda: sweep.sweep_lapsed(client)),
          ("lifting expired thread locks", lambda: lift_expired_locks(client)),
          ("lifting expired channel guards", lift_lapsed_channel_guards))
    with session() as conn:
        return sweep.seconds_to_next_expiry(conn)


def flush_pending(client):
    with session() as conn:
        memberguards.refresh(conn)
        taking_up = memberguards.unenforced(conn)
        finishing = memberguards.still_lifting(conn)
        lifted = memberguards.lifted_not_notified(conn, sweep.LIFT_LOOKBACK)

    for guard in taking_up:
        apart((f"taking up {guard['kind']} {guard['id']}",
               lambda one=guard: take_up(client, one)))
    for guard in finishing:
        apart((f"finishing the lift of {guard['kind']} {guard['id']}",
               lambda one=guard: sweep.release_now(client, one)))
    for guard in lifted:
        apart((f"releasing the lifted {guard['kind']} {guard['id']}",
               lambda one=guard: sweep.release_lifted(client, one)))


def each(cases, doing, work, client, channel_id):
    done, failing = 0, 0
    for case_id in cases:
        with session() as conn:
            try:
                work(client, conn, case_id, channel_id)
                done += 1
                failing = 0
            except Exception as failure:
                failing += 1
                log.warning("nemo: case %s %s: %s", case_id, doing, failure)
                if failing >= GIVE_UP_AFTER:
                    log.warning(
                        "nemo: giving up this sweep, %s is failing for %d case(s) in a row",
                        doing, failing,
                    )
                    break
    return done


def once(case_channel, channel_id=None):
    client = case_channel.client

    with session() as conn:
        missing = [row[0] for row in conn.execute(UNCARDED).fetchall()]
        cardless = [row[0] for row in conn.execute(CARDLESS).fetchall()]
        redraw_ids = [row[0] for row in conn.execute(WORTH_REDRAWING).fetchall()]
        unmirrored = chat.waiting_anywhere(conn)
        following = channel.waiting_follow_ups(conn)
        woke = channel.unannounced_reopens(conn)
        unshared = channel.waiting_files(conn)
        guards.refresh(conn)
        channelguards.refresh(conn)
        memberguards.refresh(conn)
        automod.refresh(conn)
        responses.refresh(conn)
        screening.refresh(conn)
        channel.refresh_channels(conn)
        destroying = guards.pending(conn)
        lifting = guards.lifting(conn)
        purging = [row[0] for row in purge.waiting(conn)]
        joining = join_requests.queued(conn)

    posted = each(missing, "still has no card", channel.post_report, client, channel_id)
    posted += each(cardless, "was opened without a card", case_queue.card, client, channel_id)
    redrawn_count = each(redraw_ids, "could not be redrawn", channel.refresh_card, client, channel_id)
    mirrored_count = each(
        unmirrored, "has chat that did not go out", channel.mirror, client, channel_id
    )
    each(unshared, "has a file that never went into the thread",
         channel.carry_files, client, channel_id)
    each(following, "has a follow-up still waiting",
         channel.carry_follow_ups, client, channel_id)
    each(redraw_ids, "has links that would not unfurl",
         channel.carry_unfurls, client, channel_id)
    each(woke, "was reopened without saying so",
         channel.post_reopen_notice, client, channel_id)
    case_channel.echo_queued()
    case_channel.tick_queued()
    case_channel.announce_fire_engine()

    for guard_id in destroying:
        apart((f"destroying guard {guard_id}", lambda id=guard_id: guard_actions.run_destroy(client, id)))
    for guard_id in lifting:
        apart((f"lifting guard {guard_id}", lambda id=guard_id: guard_actions.lift_lock(client, id)))
    for purge_id in purging:
        start_purge(client, purge_id)
    for request_id in joining:
        apart((f"joining for request {request_id}",
               lambda one=request_id: join_requests.run(client, one)))
    apart(
        ("clearing unremoved guard artifacts", lambda: guard_actions.sweep_removals(client)),
        ("resetting sessions the guard has earned", guard_actions.sweep_strikes),
        ("lifting what has run out", lambda: sweep.sweep_lapsed(client)),
        ("lifting expired channel guards", lift_lapsed_channel_guards),
        ("posting slow mode notices", lambda: slowmode.post_notices(client)),
        ("notifying manually lifted guards", lambda: sweep.sweep_lifted(client)),
        ("reclaiming released work", lambda: sweep.sweep_dropped(client)),
        ("notifying expiring guards", lambda: sweep.sweep_ending(client)),
    )

    return posted, redrawn_count, mirrored_count


def start(case_channel, stopping, channel_id=None):
    with session() as conn:
        log.info("nemo: watching %s guarded thread(s), %s guarded channel(s), "
                 "%s shushed member(s) and %s automod word(s)",
                 guards.refresh(conn), channelguards.refresh(conn),
                 memberguards.refresh(conn), automod.refresh(conn))
        responses.refresh(conn)
        screening.refresh(conn)
        channel.refresh_channels(conn)
        stranded = purge.requeue_stranded(conn)
    if stranded:
        log.info("nemo: %s purge(s) were cut off by a restart and go again: %s",
                 len(stranded), stranded)

    wake_notices = loops.draining(f"{NAME}-notices",
                                  lambda: guard_notices.drain(case_channel.client), stopping)
    wake_member_guards = loops.draining(f"{NAME}-member-guards",
                                        lambda: flush_pending(case_channel.client), stopping)
    wake_removals = loops.draining(f"{NAME}-removals",
                                   lambda: guard_removals.drain(case_channel.client, wake_notices),
                                   stopping, settle=1.0, every=5.0)
    wake_lapses = loops.timed(f"{NAME}-lapses", lambda: lift_due(case_channel.client), stopping)

    def on_notify(channel_name, payload):
        if channel_name == GUARD_NOTICE:
            wake_notices()
        elif channel_name == GUARD_REMOVE:
            wake_removals()
        elif channel_name == CHAT:
            case_channel.mirror(payload)
        elif channel_name == OUTBOX:
            apart(("echoing", case_channel.echo_queued), ("ticking", case_channel.tick_queued))
        elif channel_name == GUARD:
            with session() as conn:
                guards.refresh(conn)
            threading.Thread(
                target=guard_actions.run_destroy, args=(case_channel.client, payload),
                name=f"nemo-guard-{payload}", daemon=True,
            ).start()
            wake_lapses()
        elif channel_name == APP_SETTING:
            with session() as conn:
                channel.refresh_channels(conn)
                responses.refresh(conn)
            start_configured_joins(case_channel.client)
        elif channel_name == AUTOMOD_WORD:
            with session() as conn:
                automod.refresh(conn)
        elif channel_name == BLOCKED_DOMAIN:
            with session() as conn:
                screening.refresh(conn)
        elif channel_name == PURGE:
            start_purge(case_channel.client, payload)
        elif channel_name == JOIN_REQUEST:
            start_join_request(case_channel.client, payload)
        elif channel_name == CHANNEL_GUARD:
            with session() as conn:
                channelguards.refresh(conn)
            threading.Thread(
                target=seat_and_announce, args=(case_channel.client, payload),
                name=f"nemo-seat-{payload}", daemon=True,
            ).start()
            wake_lapses()
        elif channel_name == MEMBER_GUARD:
            wake_member_guards()
            wake_lapses()
        elif channel_name == CONVERSATION:
            apart(("catching up", lambda: case_channel.caught_up(payload)),
                  ("ticking", case_channel.tick_queued))
        else:
            case_channel.caught_up(payload)

    return (
        loops.watching(NAME,
                       (CASES, CHAT, OUTBOX, CONVERSATION, GUARD, CHANNEL_GUARD,
                        MEMBER_GUARD, APP_SETTING, AUTOMOD_WORD, PURGE,
                        GUARD_NOTICE, GUARD_REMOVE, JOIN_REQUEST, BLOCKED_DOMAIN),
                       on_notify, stopping),
        loops.sweeping(NAME, every(), lambda: once(case_channel, channel_id), stopping),
        loops.sweeping(f"{NAME}-joins", every_join_sweep(), lambda: join_sweep(case_channel, stopping),
                       stopping),
    )
