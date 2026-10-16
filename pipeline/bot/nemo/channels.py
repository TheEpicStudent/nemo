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
DEFAULT_MODE = GUARDED

PAGE = 1000
DEFAULT_JOIN_DELAY_SECONDS = 1.2
DEFAULT_PER_SWEEP = 300
MEMBER_CHANNEL_TYPES = "public_channel,private_channel"
NEEDS_INVITE = "needs an invite"
CANNOT_JOIN = ("method_not_supported_for_channel_type", "is_private")
ALREADY_IN = ("already_in_channel",)

GET_SETTING = "SELECT value FROM fd.app_settings WHERE key = %s"

UPSERT_SETTING = """
INSERT INTO fd.app_settings (key, value, changed_by, changed_at)
VALUES (%s, %s, %s, now())
ON CONFLICT (key) DO UPDATE
SET value = EXCLUDED.value, changed_by = EXCLUDED.changed_by, changed_at = now()
"""

GUARDED_CHANNELS = "SELECT DISTINCT channel_id FROM fd.channel_guards WHERE state = 'live'"

INSERT_JOIN_EVENT = """
INSERT INTO fd.channel_joins (channel_id, verb, why, by_user_id)
VALUES (%s, %s, %s, %s)
"""

UPSERT_MEMBERSHIP = """
INSERT INTO fd.channel_membership (channel_id, inside, at)
VALUES (%s, %s, now())
ON CONFLICT (channel_id) DO UPDATE
SET inside = EXCLUDED.inside, at = now()
"""

MEMBER_CHANNEL_IDS = "SELECT channel_id FROM fd.channel_membership WHERE inside"

MEMBERSHIP_STATE = "SELECT inside FROM fd.channel_membership WHERE channel_id = %s"

KNOWN_PRIVATE = "SELECT 1 FROM raw.channel_dim WHERE channel_id = %s AND visibility = %s"

SETTINGS = "SELECT key, value FROM fd.app_settings WHERE key = ANY(%s)"

LATEST_JOIN = """
SELECT verb, why FROM fd.channel_joins WHERE channel_id = %s ORDER BY at DESC, id DESC LIMIT 1
"""


def join_delay_seconds():
    try:
        return max(float(os.environ["NEMO_JOIN_PACE_SECONDS"]), 0.0)
    except (KeyError, ValueError):
        return DEFAULT_JOIN_DELAY_SECONDS


def per_sweep():
    try:
        return max(int(os.environ["NEMO_JOIN_PER_SWEEP"]), 0)
    except (KeyError, ValueError):
        return DEFAULT_PER_SWEEP


def setting(conn, key):
    row = conn.execute(GET_SETTING, (key,)).fetchone()
    return (row[0] if row else "").strip()


def set_setting(conn, key, value, by=None):
    conn.execute(UPSERT_SETTING, (key, value, by))
    return value


def split_ids(value):
    return [one.strip() for one in (value or "").split(",") if one.strip()]


def react_channels(conn):
    return set(split_ids(setting(conn, REACT_CHANNELS)))


def configured_channels(conn):
    keys = [FIREHOUSE, REPORTS, LOGS, REACT_CHANNELS, responses.AUTORESPONSE_CHANNEL]
    values = dict(conn.execute(SETTINGS, (keys,)).fetchall())
    return {channel_id for key in keys for channel_id in split_ids(values.get(key))}


def mode(conn):
    row = conn.execute(GET_SETTING, (SETTING,)).fetchone()
    configured = (row[0] if row else "").strip().lower()
    return configured if configured in MODES else DEFAULT_MODE


def set_mode(conn, join_mode, by=None):
    normalized = (join_mode or "").strip().lower()
    if normalized not in MODES:
        raise ValueError(f"{join_mode!r} is not one of {', '.join(MODES)}")

    conn.execute(UPSERT_SETTING, (SETTING, normalized, by))
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
    return _paged(client.users_conversations, types=MEMBER_CHANNEL_TYPES, exclude_archived=True)


def target_channels(client, conn, join_mode=None):
    join_mode = join_mode or mode(conn)
    configured = configured_channels(conn)
    if join_mode == OFF:
        return configured
    if join_mode == GUARDED:
        return guarded_channels(conn) | configured
    return public_channels(client) | configured


def record_join_event(conn, channel_id, verb, why=None, by=None):
    conn.execute(INSERT_JOIN_EVENT, (channel_id, verb, why, by))


def record_membership(conn, channel_id, inside_channel):
    conn.execute(UPSERT_MEMBERSHIP, (channel_id, inside_channel))


def is_inside(conn, channel_id):
    row = conn.execute(MEMBERSHIP_STATE, (channel_id,)).fetchone()
    return bool(row and row[0])


def slack_error_code(failure):
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

    record_join_event(conn, channel_id, "refused", NEEDS_INVITE, by)
    log.info("nemo: %s is private, it takes a human to invite us", channel_id)
    return False


def join(client, conn, channel_id, by=None, verb="joined"):
    if not joinable(conn, channel_id):
        log.info("nemo: %s is private, it takes a human to invite us", channel_id)
        return False

    try:
        client.conversations_join(channel=channel_id)
    except Exception as failure:
        why = slack_error_code(failure)
        if why in CANNOT_JOIN:
            return mark_private(client, conn, channel_id, by)
        if why in ALREADY_IN:
            record_membership(conn, channel_id, True)
            log.info("nemo: %s already had us in it", channel_id)
            return True
        record_join_event(conn, channel_id, "refused", why, by)
        log.info("nemo: could not join %s: %s", channel_id, why)
        return False

    record_join_event(conn, channel_id, verb, None, by)
    record_membership(conn, channel_id, True)
    return True


def waits_for_invite(conn, channel_id):
    row = conn.execute(LATEST_JOIN, (channel_id,)).fetchone()
    return bool(row) and tuple(row) == ("refused", NEEDS_INVITE)


def join_configured(client):
    with session() as conn:
        missing_ids = sorted(channel_id for channel_id in configured_channels(conn)
                        if not is_inside(conn, channel_id) and not waits_for_invite(conn, channel_id))

    joined = 0
    for channel_id in missing_ids:
        with session() as conn:
            if not joinable(conn, channel_id):
                mark_private(client, conn, channel_id, None)
            elif join(client, conn, channel_id):
                joined += 1

    if missing_ids:
        log.info("nemo: joined %s of %s configured channel(s) it was not in", joined, len(missing_ids))
    return joined


def sync_membership(conn, joined_ids):
    previous_ids = {row[0] for row in conn.execute(MEMBER_CHANNEL_IDS).fetchall()}

    for channel_id in sorted(joined_ids - previous_ids):
        conn.execute(UPSERT_MEMBERSHIP, (channel_id, True))
    for channel_id in sorted(previous_ids - joined_ids):
        conn.execute(UPSERT_MEMBERSHIP, (channel_id, False))
        record_join_event(conn, channel_id, "left", "missing at sweep")

    return len(joined_ids - previous_ids), len(previous_ids - joined_ids)


def missing_channels(client):
    with session() as conn:
        join_mode = mode(conn)
        target_ids = target_channels(client, conn, join_mode)

    joined_ids = joined_channels(client)
    with session() as conn:
        added, removed = sync_membership(conn, joined_ids)
    if added or removed:
        log.info("nemo: sits in %s channel(s), %s new, %s gone", len(joined_ids), added, removed)

    if not target_ids:
        return join_mode, []

    return join_mode, sorted(target_ids - joined_ids)


def stopped(stopping):
    return stopping is not None and stopping.is_set()


def sleep_or_stop(stopping, seconds):
    if stopping is None:
        time.sleep(seconds)
    else:
        stopping.wait(seconds)


def reconcile(client, cap=None, stopping=None):
    cap = per_sweep() if cap is None else cap
    delay = join_delay_seconds()
    attempted = set()
    join_mode, joined, refused = None, 0, 0

    while not stopped(stopping):
        join_mode, missing_ids = missing_channels(client)
        batch = [channel_id for channel_id in missing_ids if channel_id not in attempted]
        if cap:
            batch = batch[:cap]
        if not batch:
            break

        for channel_id in batch:
            if stopped(stopping):
                break
            if attempted and delay:
                sleep_or_stop(stopping, delay)
            attempted.add(channel_id)
            with session() as conn:
                if join(client, conn, channel_id):
                    joined += 1
                else:
                    refused += 1

        log.info("nemo: %s mode, joined %s channel(s), %s refused, %s still to go",
                 join_mode, joined, refused, max(len(missing_ids) - len(batch), 0))

    return join_mode, joined, refused
