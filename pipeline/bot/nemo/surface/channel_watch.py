import logging

from bot.core import session, whoami
from bot.nemo import channel, channels, internal_log
from bot.nemo.surface import on_event
from lib import channel_dim

log = logging.getLogger("bot.nemo")

VISIBILITY_BY_TYPE = {"C": channel_dim.PUBLIC, "G": channel_dim.PRIVATE}
ARCHIVE_STATE_BY_EVENT = {
    "channel_archive": True,
    "group_archive": True,
    "channel_unarchive": False,
    "group_unarchive": False,
}
REMOVED_NOTICE = "<@{actor}> removed Nemo from <#{channel}>, attempting to rejoin!"


def fetch_channel_info(client, channel_id, channel_type=None):
    defaults = {"visibility": VISIBILITY_BY_TYPE.get(channel_type)}
    try:
        channel_info = (client.conversations_info(channel=channel_id) or {}).get("channel") or {}
    except Exception as failure:
        log.info("nemo: could not look %s up: %s", channel_id, failure)
        return defaults
    return {
        "name": channel_info.get("name"),
        "archived": channel_info.get("is_archived"),
        "visibility": channel_dim.visibility_of(channel_info) or defaults["visibility"],
    }


@on_event("member_joined_channel", open_to_all=True)
def record_bot_joined(ctx):
    event = ctx.payload or {}
    channel_id = event.get("channel")
    who = event.get("user")
    if not channel_id or not who:
        return None

    if who != whoami.bot_user_id(ctx.client, "nemo"):
        return None

    channel_fields = fetch_channel_info(ctx.client, channel_id, event.get("channel_type"))
    with session() as conn:
        is_new = not channels.is_inside(conn, channel_id)
        channels.record_membership(conn, channel_id, True)
        if is_new:
            channels.record_join_event(conn, channel_id, "joined", by=event.get("inviter"))
        channel_dim.record(conn, channel_id, **channel_fields)

    log.info("nemo: seated in %s (%s)", channel_id, channel_fields.get("visibility") or "unknown")
    return channel_id


def rejoin_if_wanted(client, channel_id, by=None):
    with session() as conn:
        join_mode = channels.mode(conn)
        target_ids = channels.target_channels(client, conn, join_mode)
        channels.record_membership(conn, channel_id, False)
        if channel_id not in target_ids:
            channels.record_join_event(conn, channel_id, "left", None, by)
            log.info("nemo: left %s, which %s mode does not want back", channel_id, join_mode)
            return None

    if fetch_channel_info(client, channel_id).get("archived"):
        with session() as conn:
            channels.record_join_event(conn, channel_id, "left", "archived", by)
        log.info("nemo: %s is archived, staying out", channel_id)
        return None

    with session() as conn:
        rejoined = channels.join(client, conn, channel_id, by=by, verb="rejoined")

    log.info("nemo: put out of %s, %s", channel_id,
             "went back in" if rejoined else "could not get back in")
    post_removed_notice(client, channel_id, by)
    return rejoined


def post_removed_notice(client, channel_id, by):
    if not by or by == whoami.bot_user_id(client, "nemo"):
        return None
    with session() as conn:
        log_channel_id = channel.log_channel(conn)
    if not log_channel_id:
        return None
    try:
        internal_log.post_text(client, log_channel_id, REMOVED_NOTICE.format(actor=by, channel=channel_id))
    except Exception as failure:
        log.warning("nemo: could not post the removal from %s to the internal log: %s", channel_id, failure)
        return None
    return log_channel_id


@on_event("member_left_channel", open_to_all=True)
def record_bot_left(ctx):
    event = ctx.payload or {}
    channel_id = event.get("channel")
    who = event.get("user")
    if not channel_id or not who:
        return None

    if who != whoami.bot_user_id(ctx.client, "nemo"):
        return None

    return rejoin_if_wanted(ctx.client, channel_id)


@on_event("channel_left", open_to_all=True)
@on_event("group_left", open_to_all=True)
def record_bot_removed(ctx):
    event = ctx.payload or {}
    where = event.get("channel")
    channel_id = where.get("id") if isinstance(where, dict) else where
    if not channel_id:
        return None

    return rejoin_if_wanted(ctx.client, channel_id, by=event.get("actor_id"))


@on_event("channel_archive", open_to_all=True)
@on_event("channel_unarchive", open_to_all=True)
@on_event("group_archive", open_to_all=True)
@on_event("group_unarchive", open_to_all=True)
def record_archive_state(ctx):
    event = ctx.payload or {}
    where = event.get("channel")
    channel_id = where.get("id") if isinstance(where, dict) else where
    archived = ARCHIVE_STATE_BY_EVENT.get(ctx.entry.key)
    if not channel_id or archived is None:
        return None

    with session() as conn:
        channel_dim.record(conn, channel_id, archived=archived)

    log.info("nemo: %s was %s", channel_id, "archived" if archived else "brought back")
    return channel_id


@on_event("channel_created", open_to_all=True)
def record_channel_created(ctx):
    event = ctx.payload or {}
    channel_data = event.get("channel") or {}
    if not isinstance(channel_data, dict):
        channel_data = {"id": channel_data}
    channel_id = channel_data.get("id")
    if not channel_id:
        return None

    archived = bool(channel_data.get("is_archived"))
    with session() as conn:
        channel_dim.record(conn, channel_id, name=channel_data.get("name"), archived=archived,
                           visibility=channel_dim.PUBLIC)

    if archived:
        return None

    with session() as conn:
        if channels.mode(conn) != channels.ON:
            return None
        return channels.join(ctx.client, conn, channel_id)


@on_event("channel_rename", open_to_all=True)
@on_event("group_rename", open_to_all=True)
def record_channel_renamed(ctx):
    event = ctx.payload or {}
    where = event.get("channel")
    if not isinstance(where, dict) or not where.get("id") or not where.get("name"):
        return None

    with session() as conn:
        channel_dim.record(conn, where["id"], name=where["name"])

    log.info("nemo: %s is now #%s", where["id"], where["name"])
    return where["id"]
