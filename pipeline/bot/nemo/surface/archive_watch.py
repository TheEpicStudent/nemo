import logging
import time

from psycopg.errors import LockNotAvailable

from bot.core import session
from bot.nemo.surface import on_event
from lib import archive

log = logging.getLogger("bot.nemo")

CHANNEL_TYPES = frozenset({"channel", "group"})
LOCK_RETRY_DELAYS_SECONDS = (0.5, 2.0)


def is_channel_event(event):
    return bool(event.get("channel")) and event.get("channel_type") in CHANNEL_TYPES


@on_event("message", open_to_all=True)
def archive_channel_message(ctx):
    event = ctx.payload or {}
    if not is_channel_event(event):
        return None

    for attempt, delay in enumerate((*LOCK_RETRY_DELAYS_SECONDS, None)):
        try:
            return write_event(event)
        except LockNotAvailable:
            if delay is None:
                log.warning("nemo: channel %s stayed locked, message %s not archived after %s attempts",
                            event.get("channel"), event.get("ts"), attempt + 1)
                return None
            time.sleep(delay)
    return None


def write_event(event):
    channel_id = event["channel"]
    subtype = event.get("subtype")
    with session() as conn:
        if subtype == archive.DELETED_SUBTYPE:
            return archive.deleted(conn, channel_id, event.get("deleted_ts"), event.get("event_ts"))
        if subtype == archive.CHANGED:
            return archive.edited(conn, channel_id, event.get("message") or {})
        if event.get("hidden"):
            return None
        return archive.from_event(conn, channel_id, event)
