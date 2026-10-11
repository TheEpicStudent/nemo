import logging

from bot.core import access, session, whoami
from bot.nemo import case_actions, channel, channels, chat, case_queue, views
from bot.nemo.surface import on_event

log = logging.getLogger("bot.nemo")

OPENS = ("hourglass", "hourglass_flowing_sand", "hourglass_not_done")
CLOSES = ("white_check_mark", "heavy_check_mark", "ballot_box_with_check")
NOT_CONDUCT = channel.NOT_CONDUCT_MARKS
ENDS = CLOSES + NOT_CONDUCT
BANS = ("ban",)

CARD_OF = """
SELECT case_id FROM (
    SELECT case_id, 1 AS rank FROM fd.case_reports WHERE forwarded_ts = %(ts)s
    UNION ALL
    SELECT id, 2 FROM fd.cases WHERE card_ts = %(ts)s AND card_channel_id = %(channel)s
) found
ORDER BY rank
LIMIT 1
"""


def plain(name):
    return (name or "").split("::")[0]


def root_of(client, channel_id, ts):
    try:
        found = client.conversations_replies(
            channel=channel_id, ts=ts, limit=1, inclusive=True
        )
        message = (found.get("messages") or [{}])[0]
    except Exception as failure:
        log.info("nemo: could not read the thread above %s: %s", ts, failure)
        return ts, {}
    return message.get("thread_ts") or message.get("ts") or ts, message


def wanted(ctx, marks, needs):
    event = ctx.payload or {}
    item = event.get("item") or {}
    if item.get("type") != "message":
        return None

    channel_id, ts = item.get("channel"), item.get("ts")
    who = event.get("user")
    if not channel_id or not ts or not who:
        return None
    if plain(event.get("reaction")) not in marks:
        return None
    if who == whoami.bot_user_id(ctx.client, "nemo"):
        return None

    with session() as conn:
        if channel_id not in channels.react_channels(conn):
            return None
        may, _why = access.may(conn, who, needs)
    if not may:
        log.info("nemo: %s reacted in %s without %s", who, channel_id, needs)
        return None

    thread_ts, message = root_of(ctx.client, channel_id, ts)
    return channel_id, thread_ts, message, who


def worth_keeping(message):
    return bool(
        message.get("ts") and message.get("user") and (message.get("text") or message.get("blocks"))
    )


def keep_the_root(conn, case_id, channel_id, message):
    if not worth_keeping(message):
        return None

    chat_id, _ = chat.keep(conn, case_id, dict(message, channel=channel_id))
    return chat_id


@on_event("reaction_added", open_to_all=True)
def opened(ctx):
    asked = wanted(ctx, OPENS, "case.open")
    if asked is None:
        return None
    channel_id, thread_ts, message, who = asked

    with session() as conn:
        standing = case_queue.case_on(conn, channel_id, thread_ts)
        if standing is not None:
            log.info("nemo: %s in %s is already case %s", thread_ts, channel_id, standing)
            return standing

        case_id = case_actions.open_case(conn, None, None, who)
        keep_the_root(conn, case_id, channel_id, message)
        case_queue.post(ctx.client, conn, case_id, channel_id, thread_ts)

    log.info("nemo: case %s opened on %s in %s by %s", case_id, thread_ts, channel_id, who)
    return case_id


def closing_as(mark):
    return "not_conduct" if mark in NOT_CONDUCT else None


def after_resolve(client, case_id, resolution, who, echo=True):
    with session() as conn:
        channel.refresh_card(client, conn, case_id)
        case_queue.refresh_card(client, conn, case_id)
        if echo:
            channel.post_resolution_echo(
                client, conn, case_id, resolution, None, who,
                case_actions.resolution_echo_actions(conn, case_id),
            )


def card_case(conn, channel_id, ts):
    row = conn.execute(CARD_OF, {"ts": ts, "channel": channel_id}).fetchone()
    return row[0] if row else None


@on_event("reaction_added", open_to_all=True)
def closed_on_card(ctx):
    event = ctx.payload or {}
    item = event.get("item") or {}
    mark = plain(event.get("reaction"))
    who = event.get("user")
    if item.get("type") != "message" or mark not in ENDS or not who:
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
        resolution = case_actions.close_quietly(conn, case_id, closing_as(mark), who)

    if resolution is None:
        log.info("nemo: case %s was already resolved", case_id)
        return None
    after_resolve(ctx.client, case_id, resolution, who)
    log.info("nemo: case %s closed as %s from its card by %s", case_id, resolution, who)
    return case_id


@on_event("reaction_added", open_to_all=True)
def closed(ctx):
    asked = wanted(ctx, ENDS, "case.resolve")
    if asked is None:
        return None
    channel_id, thread_ts, _, who = asked
    mark = plain((ctx.payload or {}).get("reaction"))

    with session() as conn:
        case_id = case_queue.case_on(conn, channel_id, thread_ts)
        if case_id is None:
            return None
        resolution = case_actions.close_quietly(conn, case_id, closing_as(mark), who)

    if resolution is None:
        log.info("nemo: case %s was already resolved", case_id)
        return None
    after_resolve(ctx.client, case_id, resolution, who)
    log.info("nemo: case %s resolved from the thread by %s", case_id, who)
    return case_id


@on_event("reaction_removed", open_to_all=True)
def unreacted(ctx):
    return None


def post_ban_prompt(client, conn, case_id, target):
    thread = channel.thread_for(conn, case_id)
    if not thread:
        return None
    try:
        return client.chat_postMessage(
            channel=channel.card_room(conn, case_id),
            thread_ts=thread,
            text=f"Log an action for case {case_id}",
            blocks=views.edit.ban_prompt(case_id, target),
        )["ts"]
    except Exception as failure:
        log.warning("nemo: case %s did not get its log action prompt: %s", case_id, failure)
        return None


@on_event("reaction_added", open_to_all=True)
def banned(ctx):
    event = ctx.payload or {}
    item = event.get("item") or {}
    who = event.get("user")
    if item.get("type") != "message" or plain(event.get("reaction")) not in BANS or not who:
        return None
    if who == whoami.bot_user_id(ctx.client, "nemo"):
        return None
    channel_id, ts = item.get("channel"), item.get("ts")

    with session() as conn:
        case_id = card_case(conn, channel_id, ts)
        in_react_room = channel_id in channels.react_channels(conn)
        may, _why = access.may(conn, who, "case.act", case_id)
    if not may or (case_id is None and not in_react_room):
        return None

    target = None
    if case_id is None:
        thread_ts, message = root_of(ctx.client, channel_id, ts)
        target = message.get("user")
        with session() as conn:
            case_id = case_queue.case_on(conn, channel_id, thread_ts)
            if case_id is None:
                opens, _why = access.may(conn, who, "case.open")
                if not opens:
                    return None
                case_id = case_actions.open_case(conn, None, None, who)
                keep_the_root(conn, case_id, channel_id, message)
                case_queue.post(ctx.client, conn, case_id, channel_id, thread_ts)

    with session() as conn:
        post_ban_prompt(ctx.client, conn, case_id, target)
    log.info("nemo: %s asked to log an action on case %s", who, case_id)
    return case_id
