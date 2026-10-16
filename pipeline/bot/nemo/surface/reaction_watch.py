import logging

from bot.core import access, session, whoami
from bot.nemo import case_actions, channel, channels, chat, case_queue, views
from bot.nemo.surface import on_event

log = logging.getLogger("bot.nemo")

OPEN_REACTIONS = ("hourglass", "hourglass_flowing_sand", "hourglass_not_done")
RESOLVE_REACTIONS = ("white_check_mark", "heavy_check_mark", "ballot_box_with_check", "white_tick", "check")
RESOLVE_REACTION_PREFIX = "check-"
NOT_CONDUCT_REACTIONS = channel.NOT_CONDUCT_MARKS
BAN_REACTIONS = ("ban",)

CARD_CASE = """
SELECT case_id FROM (
    SELECT case_id, 1 AS priority FROM fd.case_reports WHERE forwarded_ts = %(ts)s
    UNION ALL
    SELECT id, 2 FROM fd.cases WHERE card_ts = %(ts)s AND card_channel_id = %(channel)s
) matching_case
ORDER BY priority
LIMIT 1
"""


def plain(name):
    return (name or "").split("::")[0]


def is_open_reaction(name):
    return name in OPEN_REACTIONS


def is_resolve_reaction(name):
    return name in RESOLVE_REACTIONS or (
        name.startswith(RESOLVE_REACTION_PREFIX) and len(name) > len(RESOLVE_REACTION_PREFIX)
    )


def is_close_reaction(name):
    return is_resolve_reaction(name) or name in NOT_CONDUCT_REACTIONS


def thread_root(client, channel_id, ts):
    try:
        response = client.conversations_replies(
            channel=channel_id, ts=ts, limit=1, inclusive=True
        )
        message = (response.get("messages") or [{}])[0]
    except Exception as failure:
        log.info("nemo: could not read the thread above %s: %s", ts, failure)
        return ts, {}
    return message.get("thread_ts") or message.get("ts") or ts, message


def reaction_target(ctx, matches, capability, resolve_root=True):
    event = ctx.payload or {}
    item = event.get("item") or {}
    if item.get("type") != "message":
        return None

    channel_id, ts = item.get("channel"), item.get("ts")
    who = event.get("user")
    if not channel_id or not ts or not who:
        return None
    if not matches(plain(event.get("reaction"))):
        return None
    if who == whoami.bot_user_id(ctx.client, "nemo"):
        return None

    with session() as conn:
        if channel_id not in channels.react_channels(conn):
            return None
        may, _why = access.may(conn, who, capability)
    if not may:
        log.info("nemo: %s reacted in %s without %s", who, channel_id, capability)
        return None

    if not resolve_root:
        return channel_id, ts, {}, who
    thread_ts, message = thread_root(ctx.client, channel_id, ts)
    return channel_id, thread_ts, message, who


def is_storable(message):
    return bool(
        message.get("ts") and message.get("user") and (message.get("text") or message.get("blocks"))
    )


def store_root_message(conn, case_id, channel_id, message):
    if not is_storable(message):
        return None

    chat_id, _ = chat.store_message(conn, case_id, dict(message, channel=channel_id))
    return chat_id


@on_event("reaction_added", open_to_all=True)
def open_case_on_reaction(ctx):
    target = reaction_target(ctx, is_open_reaction, "case.open")
    if target is None:
        return None
    channel_id, thread_ts, message, who = target

    with session() as conn:
        existing_case_id = case_queue.case_for_thread(conn, channel_id, thread_ts)
        if existing_case_id is not None:
            log.info("nemo: %s in %s is already case %s", thread_ts, channel_id, existing_case_id)
            return existing_case_id

        case_id = case_actions.open_case(conn, None, None, who)
        store_root_message(conn, case_id, channel_id, message)
        case_queue.post(ctx.client, conn, case_id, channel_id, thread_ts)

    log.info("nemo: case %s opened on %s in %s by %s", case_id, thread_ts, channel_id, who)
    return case_id


def resolution_for(reaction):
    return "not_conduct" if reaction in NOT_CONDUCT_REACTIONS else None


def after_resolve(client, case_id, resolution, who, post_log=True):
    with session() as conn:
        channel.refresh_card(client, conn, case_id)
        case_queue.refresh_card(client, conn, case_id)
        if post_log:
            channel.post_resolution_log(
                client, conn, case_id, resolution, None, who,
                case_actions.resolution_log_actions(conn, case_id),
            )


def card_case(conn, channel_id, ts):
    row = conn.execute(CARD_CASE, {"ts": ts, "channel": channel_id}).fetchone()
    return row[0] if row else None


@on_event("reaction_added", open_to_all=True)
def close_case_on_card_reaction(ctx):
    event = ctx.payload or {}
    item = event.get("item") or {}
    reaction = plain(event.get("reaction"))
    who = event.get("user")
    if item.get("type") != "message" or not is_close_reaction(reaction) or not who:
        return None
    if who == whoami.bot_user_id(ctx.client, "nemo"):
        return None

    with session() as conn:
        case_id = card_case(conn, item.get("channel"), item.get("ts"))
        if case_id is None:
            return None
        may, _why = access.may(conn, who, "case.resolve", case_id)
        if not may:
            log.info("nemo: %s reacted on case %s without case.resolve", who, case_id)
            return None
        resolution = case_actions.close_without_notice(conn, case_id, resolution_for(reaction), who)

    if resolution is None:
        log.info("nemo: case %s was already resolved", case_id)
        return None
    after_resolve(ctx.client, case_id, resolution, who)
    log.info("nemo: case %s closed as %s from its card by %s", case_id, resolution, who)
    return case_id


@on_event("reaction_added", open_to_all=True)
def close_case_on_root_reaction(ctx):
    target = reaction_target(ctx, is_close_reaction, "case.resolve", resolve_root=False)
    if target is None:
        return None
    channel_id, root_ts, _, who = target
    reaction = plain((ctx.payload or {}).get("reaction"))

    with session() as conn:
        case_id = case_queue.case_for_root(conn, channel_id, root_ts)
        if case_id is None:
            return None
        resolution = case_actions.close_without_notice(conn, case_id, resolution_for(reaction), who)

    if resolution is None:
        log.info("nemo: case %s was already resolved", case_id)
        return None
    after_resolve(ctx.client, case_id, resolution, who)
    log.info("nemo: case %s resolved from the thread by %s", case_id, who)
    return case_id


@on_event("reaction_removed", open_to_all=True)
def ignore_reaction_removed(ctx):
    return None


def post_ban_prompt(client, conn, case_id, target):
    thread = channel.thread_for(conn, case_id)
    if not thread:
        return None
    try:
        return client.chat_postMessage(
            channel=channel.card_channel_for(conn, case_id),
            thread_ts=thread,
            text=f"Log action · case {case_id}",
            blocks=views.edit.ban_prompt(case_id, target),
        )["ts"]
    except Exception as failure:
        log.warning("nemo: case %s did not get its log action prompt: %s", case_id, failure)
        return None


@on_event("reaction_added", open_to_all=True)
def prompt_action_log_on_ban(ctx):
    event = ctx.payload or {}
    item = event.get("item") or {}
    who = event.get("user")
    if item.get("type") != "message" or plain(event.get("reaction")) not in BAN_REACTIONS or not who:
        return None
    if who == whoami.bot_user_id(ctx.client, "nemo"):
        return None
    channel_id, ts = item.get("channel"), item.get("ts")

    with session() as conn:
        case_id = card_case(conn, channel_id, ts)
        in_react_channel = channel_id in channels.react_channels(conn)
        may, _why = access.may(conn, who, "case.act", case_id)
    if not may or (case_id is None and not in_react_channel):
        return None

    target = None
    if case_id is None:
        thread_ts, message = thread_root(ctx.client, channel_id, ts)
        target = message.get("user")
        with session() as conn:
            case_id = case_queue.case_for_thread(conn, channel_id, thread_ts)
            if case_id is None:
                opens, _why = access.may(conn, who, "case.open")
                if not opens:
                    return None
                case_id = case_actions.open_case(conn, None, None, who)
                store_root_message(conn, case_id, channel_id, message)
                case_queue.post(ctx.client, conn, case_id, channel_id, thread_ts)

    with session() as conn:
        post_ban_prompt(ctx.client, conn, case_id, target)
    log.info("nemo: %s asked to log an action on case %s", who, case_id)
    return case_id
