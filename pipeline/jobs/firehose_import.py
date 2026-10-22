import collections
import datetime as dt
import logging
import os

import psycopg

from bot.core import session
from lyla import link, status, store

log = logging.getLogger("firehose")

SOURCE = "firehose"
URL = "FIREHOSE_DATABASE_URL"
PASS_SECONDS = 15
RETRY_SECONDS = 60
SHUSH = "shush"
CHANNEL_BAN = "channel_ban"
SHUSHES = "Bans"
CHANNEL_BANS = "User"
LIFTED_REASON = "Lifted in Firehose"
DEFAULT_REASON = "Firehose"

FIREHOSE_SHUSHES = 'SELECT id, "user", NULL, reason, admin, "expiresAt" FROM "Bans"'

FIREHOSE_CHANNEL_BANS = 'SELECT id, "user", channel, reason, admin, "expiresAt" FROM "User"'

MAPPED = """
SELECT m.source_table, m.source_key, g.id, g.kind, g.subject_id, g.channel_id, g.state,
       g.enforced_by, g.expires_at, g.reason
FROM fd.import_map m
JOIN fd.member_guards g ON g.id = m.entity_id
WHERE m.source_app = 'firehose' AND m.entity_table = 'member_guards'
"""

LIVE_GUARD = """
SELECT id, enforced_by, expires_at, reason FROM fd.member_guards
WHERE subject_id = %s AND kind = %s AND coalesce(channel_id, '') = coalesce(%s, '')
  AND state IN ('live', 'lifting')
"""

OPEN = """
INSERT INTO fd.member_guards
    (kind, subject_id, channel_id, opened_by, reason, expires_at, enforced_by, enforcement_status)
VALUES (%s, %s, %s, %s, %s, %s, 'firehose', 'held')
ON CONFLICT DO NOTHING
RETURNING id
"""

RETIME = """
UPDATE fd.member_guards SET expires_at = %s, reason = %s, updated_at = now()
WHERE id = %s AND enforced_by = 'firehose' AND state = 'live'
"""

LIFT = """
UPDATE fd.member_guards
SET state = 'lifted', lifted_at = now(), lifted_by = %s, lift_reason = %s, updated_at = now()
WHERE id = %s AND enforced_by = 'firehose' AND state = 'live'
RETURNING id
"""

Key = collections.namedtuple("Key", "kind subject_id channel_id")


def connect():
    return psycopg.connect(os.environ[URL], options="-c default_transaction_read_only=on")


def utc(value):
    return value.replace(tzinfo=dt.UTC) if value and value.tzinfo is None else value


def live_rows(firehose, now=None):
    now = now or dt.datetime.now(dt.UTC)
    grouped = collections.defaultdict(list)
    for table, kind, query in ((SHUSHES, SHUSH, FIREHOSE_SHUSHES),
                               (CHANNEL_BANS, CHANNEL_BAN, FIREHOSE_CHANNEL_BANS)):
        for row_id, user_id, channel_id, reason, admin, expires_at in firehose.execute(query).fetchall():
            expires_at = utc(expires_at)
            if not user_id or (kind == CHANNEL_BAN and not channel_id):
                continue
            if expires_at is not None and expires_at <= now:
                continue
            grouped[Key(kind, user_id.strip(), channel_id)].append(
                {"table": table, "id": row_id, "reason": reason, "admin": admin, "expires_at": expires_at})
    firehose.commit()
    return grouped


def wanted(rows):
    ends = [row["expires_at"] for row in rows]
    expires_at = None if any(end is None for end in ends) else max(ends)
    reason = next((row["reason"].strip() for row in rows if (row["reason"] or "").strip()), DEFAULT_REASON)
    opener = next((row["admin"] for row in rows if row["admin"]), SOURCE)
    return expires_at, reason, opener


def mirror(firehose):
    summary = collections.Counter()
    grouped = live_rows(firehose)
    with session() as conn:
        mapped = conn.execute(MAPPED).fetchall()
    guards_by_key = {}
    for _table, _key, guard_id, kind, subject_id, channel_id, state, enforced_by, _end, _why in mapped:
        if state == "live" and enforced_by == SOURCE:
            guards_by_key[Key(kind, subject_id, channel_id)] = guard_id

    for key, rows in grouped.items():
        expires_at, reason, opener = wanted(rows)
        with session() as conn:
            guard_id = guards_by_key.get(key)
            if guard_id is None:
                existing = conn.execute(LIVE_GUARD, (key.subject_id, key.kind, key.channel_id)).fetchone()
                if existing and existing[1] != SOURCE:
                    summary["held_by_nemo"] += 1
                    continue
                guard_id = existing[0] if existing else None
            if guard_id is None:
                created = conn.execute(OPEN, (key.kind, key.subject_id, key.channel_id, opener, reason,
                                              expires_at)).fetchone()
                if created is None:
                    continue
                guard_id = created[0]
                store.record(conn, "member_guard", guard_id, "opened", opener, app=SOURCE,
                             after={"kind": key.kind, "subject_id": key.subject_id,
                                    "channel_id": key.channel_id, "enforced_by": SOURCE,
                                    "expires_at": str(expires_at) if expires_at else None},
                             subject_user_id=key.subject_id)
                summary["opened"] += 1
            else:
                current = conn.execute(LIVE_GUARD, (key.subject_id, key.kind, key.channel_id)).fetchone()
                if current and (current[2] != expires_at or current[3] != reason):
                    conn.execute(RETIME, (expires_at, reason, guard_id))
                    summary["retimed"] += 1
            for row in rows:
                store.put(conn, row["table"], row["id"], "member_guards", guard_id, app=SOURCE)
        guards_by_key[key] = guard_id

    kept = set(grouped)
    live_ids = {(row["table"], str(row["id"])) for rows in grouped.values() for row in rows}
    for table, source_key, guard_id, kind, subject_id, channel_id, state, enforced_by, _end, _why in mapped:
        key = Key(kind, subject_id, channel_id)
        with session() as conn:
            if key not in kept and state == "live" and enforced_by == SOURCE:
                if conn.execute(LIFT, (SOURCE, LIFTED_REASON, guard_id)).fetchone():
                    store.record(conn, "member_guard", guard_id, "lifted", SOURCE, app=SOURCE,
                                 before={"state": "live"},
                                 after={"state": "lifted", "lift_reason": LIFTED_REASON},
                                 subject_user_id=subject_id)
                    summary["lifted"] += 1
            if (table, source_key) not in live_ids:
                store.forget(conn, table, source_key, app=SOURCE)
    return summary


def serve(stopping):
    firehose = None
    while not stopping.is_set():
        with session() as conn:
            on = link.is_on(conn)
        if not on:
            if firehose is not None:
                firehose.close()
            firehose = None
            stopping.wait(PASS_SECONDS)
            continue
        try:
            if firehose is None or firehose.closed:
                firehose = connect()
            summary = mirror(firehose)
            with session() as conn:
                status.ran(conn, status.FIREHOSE)
            if summary:
                log.info("firehose: %s", dict(summary))
        except Exception as failure:
            log.exception("firehose: the mirror pass failed, trying again in %ss", RETRY_SECONDS)
            with session() as conn:
                status.ran(conn, status.FIREHOSE, failure)
            if firehose is not None:
                firehose.close()
            firehose = None
            stopping.wait(RETRY_SECONDS)
            continue
        stopping.wait(PASS_SECONDS)
    if firehose is not None:
        firehose.close()
