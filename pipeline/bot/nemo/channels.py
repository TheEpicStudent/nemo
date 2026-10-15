import logging
import os
import time

from bot.core import session
from bot.nemo import responses
from lib import channel_dim

log = logging.getLogger("bot.nemo")

ON = "on"
GUARDED = "guarded"
OFF = "off"
MODES = (ON, GUARDED, OFF)

SETTING = "nemo.join_mode"
FIREHOUSE = "nemo.firehouse_channel"
REPORTS = "nemo.reports_channel"
LOGS = "nemo.log_channel"
REACT_CHANNELS = "nemo.case_react_channels"
SWEEP_SOON_HOURS = "nemo.sweep_soon_hours"
SWEEP_TELLS_MEMBER = "nemo.sweep_tells_member"
FALL_BACK = GUARDED

PAGE = 1000
DEFAULT_PACE = 1.2
DEFAULT_PER_SWEEP = 300
SEATED_TYPES = "public_channel,private_channel"
NEEDS_INVITE = "needs an invite"
CANNOT_JOIN = ("method_not_supported_for_channel_type", "is_private")
ALREADY_IN = ("already_in_channel",)

HOW = "SELECT value FROM fd.app_settings WHERE key = %s"

SET_HOW = """
INSERT INTO fd.app_settings (key, value, changed_by, changed_at)
VALUES (%s, %s, %s, now())
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value, changed_by = EXCLUDED.changed_by, changed_at = now()
"""

GUARDED_CHANNELS = "SELECT DISTINCT channel_id FROM fd.channel_guards WHERE state = 'live'"

NOTED = """
INSERT INTO fd.channel_joins (channel_id, verb, why, by_user_id)
VALUES (%s, %s, %s, %s)
"""

SEATED = """
INSERT INTO fd.channel_membership (channel_id, inside, at)
VALUES (%s, %s, now())
ON CONFLICT (channel_id) DO UPDATE
SET inside = EXCLUDED.inside, at = now()
"""

WAS_INSIDE = "SELECT channel_id FROM fd.channel_membership WHERE inside"

INSIDE = "SELECT inside FROM fd.channel_membership WHERE channel_id = %s"

KNOWN_PRIVATE = "SELECT 1 FROM raw.channel_dim WHERE channel_id = %s AND visibility = %s"

SETTINGS = "SELECT key, value FROM fd.app_settings WHERE key = ANY(%s)"

LATEST_JOIN = """
SELECT verb, why FROM fd.channel_joins WHERE channel_id = %s ORDER BY at DESC, id DESC LIMIT 1
"""


def pace():
    try:
        return max(float(os.environ["NEMO_JOIN_PACE_SECONDS"]), 0.0)
    except (KeyError, ValueError):
        return DEFAULT_PACE


def per_sweep():
    try:
        return max(int(os.environ["NEMO_JOIN_PER_SWEEP"]), 0)
    except (KeyError, ValueError):
        return DEFAULT_PER_SWEEP


def setting(conn, key):
    row = conn.execute(HOW, (key,)).fetchone()
    return (row[0] if row else "").strip()


def set_setting(conn, key, value, by=None):
    conn.execute(SET_HOW, (key, value, by))
    return value


def listed(value):
    return [one.strip() for one in (value or "").split(",") if one.strip()]


def react_channels(conn):
    return set(listed(setting(conn, REACT_CHANNELS)))


def configured_channels(conn):
    keys = [FIREHOUSE, REPORTS, LOGS, REACT_CHANNELS, responses.AUTORESPONSE_CHANNEL]
    values = dict(conn.execute(SETTINGS, (keys,)).fetchall())
    return {channel_id for key in keys for channel_id in listed(values.get(key))}


def mode(conn):
    row = conn.execute(HOW, (SETTING,)).fetchone()
    configured = (row[0] if row else "").strip().lower()
    return configured if configured in MODES else FALL_BACK


def set_mode(conn, how, by=None):
    normalized = (how or "").strip().lower()
    if normalized not in MODES:
        raise ValueError(f"{how!r} is not one of {', '.join(MODES)}")

    conn.execute(SET_HOW, (SETTING, normalized, by))
    return normalized


def guarded_channels(conn):
    return {row[0] for row in conn.execute(GUARDED_CHANNELS).fetchall()}


def team():
    return os.environ.get("SLACK_TEAM_ID", "").strip()


def _paged(call, **params):
    where = team()
    if where:
        params["team_id"] = where

    channel_ids = set()
    cursor = None
    while True:
        response = call(limit=PAGE, cursor=cursor, **params)
        for channel in response.get("channels") or []:
            if channel.get("id") and not channel.get("is_archived"):
                channel_ids.add(channel["id"])
        cursor = (response.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return channel_ids


def public_channels(client):
    return _paged(client.conversations_list, types="public_channel", exclude_archived=True)


def joined_channels(client):
    return _paged(client.users_conversations, types=SEATED_TYPES, exclude_archived=True)


def target_channels(client, conn, how=None):
    how = how or mode(conn)
    configured = configured_channels(conn)
    if how == OFF:
        return configured
    if how == GUARDED:
        return guarded_channels(conn) | configured
    return public_channels(client) | configured


def noted(conn, channel_id, verb, why=None, by=None):
    conn.execute(NOTED, (channel_id, verb, why, by))


def record_membership(conn, channel_id, inside):
    conn.execute(SEATED, (channel_id, inside))


def inside(conn, channel_id):
    row = conn.execute(INSIDE, (channel_id,)).fetchone()
    return bool(row and row[0])


def refusal(failure):
    response = getattr(failure, "response", None)
    data = getattr(response, "data", None) or {}
    return data.get("error") or type(failure).__name__


def joinable(conn, channel_id):
    return conn.execute(KNOWN_PRIVATE, (channel_id, channel_dim.PRIVATE)).fetchone() is None


def is_member(client, channel_id):
    try:
        channel_info = (client.conversations_info(channel=channel_id) or {}).get("channel") or {}
    except Exception as failure:
        log.info("nemo: could not tell whether we sit in %s: %s", channel_id, failure)
        return None
    return channel_info.get("is_member")


def mark_private(client, conn, channel_id, by):
    channel_dim.record(conn, channel_id, visibility=channel_dim.PRIVATE)
    if is_member(client, channel_id):
        record_membership(conn, channel_id, True)
        log.info("nemo: %s is private and we are already sitting in it", channel_id)
        return True

    noted(conn, channel_id, "refused", NEEDS_INVITE, by)
    log.info("nemo: %s is private, it takes a human to invite us", channel_id)
    return False


def join(client, conn, channel_id, by=None, verb="joined"):
    if not joinable(conn, channel_id):
        log.info("nemo: %s is private, it takes a human to invite us", channel_id)
        return False

    try:
        client.conversations_join(channel=channel_id)
    except Exception as failure:
        why = refusal(failure)
        if why in CANNOT_JOIN:
            return mark_private(client, conn, channel_id, by)
        if why in ALREADY_IN:
            record_membership(conn, channel_id, True)
            log.info("nemo: %s already had us in it", channel_id)
            return True
        noted(conn, channel_id, "refused", why, by)
        log.info("nemo: could not join %s: %s", channel_id, why)
        return False

    noted(conn, channel_id, verb, None, by)
    record_membership(conn, channel_id, True)
    return True


def waits_for_invite(conn, channel_id):
    row = conn.execute(LATEST_JOIN, (channel_id,)).fetchone()
    return bool(row) and tuple(row) == ("refused", NEEDS_INVITE)


def join_configured(client):
    with session() as conn:
        absent = sorted(channel_id for channel_id in configured_channels(conn)
                        if not inside(conn, channel_id) and not waits_for_invite(conn, channel_id))

    joined = 0
    for channel_id in absent:
        with session() as conn:
            if not joinable(conn, channel_id):
                mark_private(client, conn, channel_id, None)
            elif join(client, conn, channel_id):
                joined += 1

    if absent:
        log.info("nemo: joined %s of %s configured channel(s) it was not in", joined, len(absent))
    return joined


def sync_membership(conn, joined_ids):
    previous_ids = {row[0] for row in conn.execute(WAS_INSIDE).fetchall()}

    for channel_id in sorted(joined_ids - previous_ids):
        conn.execute(SEATED, (channel_id, True))
    for channel_id in sorted(previous_ids - joined_ids):
        conn.execute(SEATED, (channel_id, False))
        noted(conn, channel_id, "left", "gone at the sweep")

    return len(joined_ids - previous_ids), len(previous_ids - joined_ids)


def missing(client):
    with session() as conn:
        how = mode(conn)
        target_ids = target_channels(client, conn, how)

    joined_ids = joined_channels(client)
    with session() as conn:
        added, removed = sync_membership(conn, joined_ids)
    if added or removed:
        log.info("nemo: sits in %s channel(s), %s new, %s gone", len(joined_ids), added, removed)

    if not target_ids:
        return how, []

    return how, sorted(target_ids - joined_ids)


def reconcile(client, cap=None):
    how, absent = missing(client)
    if not absent:
        return how, 0, 0

    cap = per_sweep() if cap is None else cap
    delay = pace()
    joined = refused = 0

    for index, channel_id in enumerate(absent[:cap] if cap else absent):
        if index and delay:
            time.sleep(delay)
        with session() as conn:
            if join(client, conn, channel_id):
                joined += 1
            else:
                refused += 1

    log.info("nemo: %s mode, joined %s channel(s), %s refused, %s still to go",
             how, joined, refused, max(len(absent) - joined - refused, 0))
    return how, joined, refused
