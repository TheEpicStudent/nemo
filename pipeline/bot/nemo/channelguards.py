import datetime as dt
import json
import threading

from bot.core import audit

BOT_ALLOWLIST = "bot_allowlist"
READONLY = "readonly"
SLOWMODE = "slowmode"
ACCOUNT_AGE = "account_age"
KINDS = (BOT_ALLOWLIST, READONLY, SLOWMODE, ACCOUNT_AGE)
CHANNEL_WIDE = ""

LIVE = """
SELECT g.kind, g.channel_id, g.thread_ts, g.id, g.settings, g.expires_at,
       coalesce(array_agg(a.subject_id) FILTER (WHERE a.subject_id IS NOT NULL), '{}')
FROM fd.channel_guards g
LEFT JOIN fd.channel_guard_allows a ON a.guard_id = g.id
WHERE g.state = 'live'
GROUP BY g.kind, g.channel_id, g.thread_ts, g.id, g.settings, g.expires_at
"""

LIVE_GUARD = """
SELECT id, kind, channel_id, state, opened_by, case_id
FROM fd.channel_guards
WHERE channel_id = %s AND kind = %s AND thread_ts = '' AND state = 'live'
"""

SLOWMODE_ROW = """
SELECT id, settings, expires_at, reason, opened_by
FROM fd.channel_guards
WHERE channel_id = %s AND thread_ts = %s AND kind = 'slowmode' AND state = 'live'
"""

OPEN_SLOWMODE = """
INSERT INTO fd.channel_guards
    (kind, channel_id, thread_ts, settings, opened_by, reason, expires_at, notice_wanted)
VALUES ('slowmode', %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT DO NOTHING
RETURNING id
"""

UPDATE_SLOWMODE = """
UPDATE fd.channel_guards
SET settings = settings || %s::jsonb, reason = %s, expires_at = %s, updated_at = now()
WHERE id = %s AND state = 'live'
RETURNING id
"""

LIFT_LAPSED = """
UPDATE fd.channel_guards
SET state = 'lifted', lifted_at = now(), updated_at = now()
WHERE state = 'live' AND expires_at IS NOT NULL AND expires_at <= now()
RETURNING id, kind, channel_id, thread_ts
"""

DISALLOW_ALL_BUT = """
DELETE FROM fd.channel_guard_allows
WHERE guard_id = %s AND NOT (subject_id = ANY(%s))
RETURNING subject_id
"""

OPEN = """
INSERT INTO fd.channel_guards (kind, channel_id, opened_by, case_id)
VALUES (%s, %s, %s, %s)
ON CONFLICT DO NOTHING
RETURNING id
"""

LIFT = """
UPDATE fd.channel_guards
SET state = 'lifted', lifted_at = now(), lifted_by = %s, updated_at = now()
WHERE id = %s AND state = 'live'
RETURNING channel_id
"""

ALLOW = """
INSERT INTO fd.channel_guard_allows (guard_id, subject_id, label, added_by)
VALUES (%s, %s, %s, %s)
ON CONFLICT (guard_id, subject_id) DO UPDATE
SET label = coalesce(EXCLUDED.label, fd.channel_guard_allows.label)
RETURNING subject_id
"""

DISALLOW = """
DELETE FROM fd.channel_guard_allows WHERE guard_id = %s AND subject_id = %s
RETURNING subject_id
"""

ALLOWED = """
SELECT subject_id, label, added_by, added_at
FROM fd.channel_guard_allows WHERE guard_id = %s ORDER BY added_at
"""

OPEN_NOTICE_THREAD = """
SELECT id, parent_ts FROM fd.channel_guard_notice_threads
WHERE guard_id = %s AND subject_id = %s
  AND last_event_at > now() - %s AND opened_at > now() - %s
ORDER BY last_event_at DESC LIMIT 1
"""

OPEN_NEW_NOTICE_THREAD = """
INSERT INTO fd.channel_guard_notice_threads
    (guard_id, subject_id, parent_ts, deleted_count, kicked_count)
VALUES (%s, %s, %s, %s, %s)
RETURNING id
"""

ADD_NOTICE_COUNTS = """
UPDATE fd.channel_guard_notice_threads
SET deleted_count = deleted_count + %s, kicked_count = kicked_count + %s, last_event_at = now()
WHERE id = %s
RETURNING deleted_count, kicked_count
"""

INSERT_EVENT = """
INSERT INTO fd.channel_guard_events
    (guard_id, channel_id, subject_id, bot_id, label, verb, message_text, message_ts, permalink, app_id,
     detail, notice_wanted, remove_pending)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
"""

NOTICE_GROUPS = """
SELECT guard_id, subject_id
FROM fd.channel_guard_events
WHERE notice_wanted AND noticed_at IS NULL AND notice_attempts < %s AND NOT remove_pending
GROUP BY guard_id, subject_id
ORDER BY min(id)
LIMIT %s
"""

CLAIM_NOTICES = """
SELECT id, channel_id, subject_id, verb, label, message_text, message_ts, permalink, app_id, detail
FROM fd.channel_guard_events
WHERE guard_id = %s AND subject_id = %s
  AND notice_wanted AND noticed_at IS NULL AND notice_attempts < %s AND NOT remove_pending
ORDER BY id
LIMIT %s
FOR UPDATE SKIP LOCKED
"""

MARK_NOTICED = """
UPDATE fd.channel_guard_events SET noticed_at = now() WHERE id = ANY(%s)
"""

NOTICE_FAILED = """
UPDATE fd.channel_guard_events SET notice_attempts = notice_attempts + 1
WHERE id = ANY(%s)
RETURNING id, notice_attempts
"""

NOTICE_FIELDS = ("id", "channel_id", "subject_id", "verb", "label", "message_text", "message_ts",
                 "permalink", "app_id", "detail")

CLAIM_REMOVALS = """
SELECT id, channel_id, message_ts
FROM fd.channel_guard_events
WHERE remove_pending
ORDER BY id
LIMIT %s
FOR UPDATE SKIP LOCKED
"""

CLEAR_REMOVE_PENDING = """
UPDATE fd.channel_guard_events SET remove_pending = false, detail = NULL WHERE id = %s
"""

REMOVAL_FAILED = """
UPDATE fd.channel_guard_events
SET remove_attempts = remove_attempts + 1,
    detail = %s,
    remove_pending = remove_attempts + 1 < %s,
    verb = CASE WHEN remove_attempts + 1 < %s THEN verb ELSE 'let_past' END
WHERE id = %s
RETURNING remove_pending
"""

_guards = {}
_loaded = False
_lock = threading.Lock()


class LiveGuard:
    def __init__(self, guard_id, settings, allowed, expires_at=None):
        self.guard_id = guard_id
        self.settings = settings or {}
        self.allowed = allowed
        self.expires_at = expires_at

    def in_force(self, now=None):
        return self.expires_at is None or self.expires_at > (now or dt.datetime.now(dt.UTC))

    def __iter__(self):
        return iter((self.guard_id, self.allowed))

    def allows(self, *ids):
        return any(one and one in self.allowed for one in ids)

    def seconds(self):
        return int(self.settings.get("seconds") or 0)

    def threads(self):
        return self.settings.get("threads") is True

    def min_age_days(self):
        return int(self.settings.get("min_age_days") or 0)


def refresh(conn):
    global _loaded
    guards_by_key = {
        (row[0], row[1], row[2]): LiveGuard(row[3], row[4], frozenset(row[6] or ()), row[5])
        for row in conn.execute(LIVE).fetchall()
    }
    with _lock:
        _guards.clear()
        _guards.update(guards_by_key)
        _loaded = True
    return sum(1 for kind, _, _ in guards_by_key if kind == BOT_ALLOWLIST)


def in_force(guard):
    return guard if guard is not None and guard.in_force() else None


def active_guard(channel_id, kind=BOT_ALLOWLIST):
    with _lock:
        if not _loaded:
            return None
        return in_force(_guards.get((kind, channel_id, CHANNEL_WIDE)))


def thread_slowmode(channel_id, thread_ts):
    if not thread_ts:
        return None
    with _lock:
        if not _loaded:
            return None
        return in_force(_guards.get((SLOWMODE, channel_id, thread_ts)))


def is_guarded(channel_id):
    with _lock:
        if not _loaded:
            return False
        return any(guarded_id == channel_id for _, guarded_id, _ in _guards)


def allows(channel_id, *ids, kind=BOT_ALLOWLIST):
    guard = active_guard(channel_id, kind)
    if guard is None:
        return True

    return guard.allows(*ids)


def live_guard(conn, channel_id, kind=BOT_ALLOWLIST):
    return conn.execute(LIVE_GUARD, (channel_id, kind)).fetchone()


def allowed(conn, guard_id):
    return conn.execute(ALLOWED, (guard_id,)).fetchall()


def slowmode_row(conn, channel_id, thread_ts=CHANNEL_WIDE):
    row = conn.execute(SLOWMODE_ROW, (channel_id, thread_ts)).fetchone()
    if row is None:
        return None
    guard_id, settings, expires_at, reason, opened_by = row
    exempt_ids = [one[0] for one in allowed(conn, guard_id)]
    return {"id": guard_id, "seconds": int((settings or {}).get("seconds") or 0),
            "expires_at": expires_at, "reason": reason, "opened_by": opened_by,
            "exempt": exempt_ids}


def open_slowmode(conn, channel_id, thread_ts, seconds, by, reason, expires_at, notice_wanted=False):
    row = conn.execute(OPEN_SLOWMODE, (
        channel_id, thread_ts, json.dumps({"seconds": seconds}), by, reason, expires_at, notice_wanted,
    )).fetchone()
    if row is None:
        return None

    guard_id = row[0]
    audit.record(
        conn, "channel_guard", guard_id, "opened", by,
        after={"kind": SLOWMODE, "channel_id": channel_id, "thread_ts": thread_ts or None,
               "seconds": seconds, "reason": reason,
               "expires_at": str(expires_at) if expires_at else None},
    )
    return guard_id


def update_slowmode(conn, current, seconds, by, reason, expires_at):
    row = conn.execute(UPDATE_SLOWMODE, (
        json.dumps({"seconds": seconds}), reason, expires_at, current["id"],
    )).fetchone()
    if row is None:
        return None

    audit.record(
        conn, "channel_guard", current["id"], "tuned", by,
        before={"seconds": current["seconds"], "reason": current["reason"],
                "expires_at": str(current["expires_at"]) if current["expires_at"] else None},
        after={"seconds": seconds, "reason": reason,
               "expires_at": str(expires_at) if expires_at else None},
    )
    return row[0]


def set_allows(conn, guard_id, subject_ids, by):
    wanted = list(dict.fromkeys(one for one in subject_ids if one))
    existing_ids = {row[0] for row in allowed(conn, guard_id)}
    for subject_id in (row[0] for row in conn.execute(DISALLOW_ALL_BUT, (guard_id, wanted)).fetchall()):
        audit.record(conn, "channel_allow", guard_id, "removed", by,
                     before={"subject_id": subject_id}, after=None)
    for subject_id in wanted:
        if subject_id not in existing_ids:
            allow(conn, guard_id, subject_id, by)
    return wanted


def lift_lapsed(conn):
    lifted = conn.execute(LIFT_LAPSED).fetchall()
    for guard_id, kind, channel_id, thread_ts in lifted:
        audit.record(conn, "channel_guard", guard_id, "lifted", "system", actor_kind="system",
                     before={"state": "live"}, after={"state": "lifted", "kind": kind,
                                                       "channel_id": channel_id,
                                                       "thread_ts": thread_ts or None})
    return lifted


def open_guard(conn, channel_id, by, case_id=None, kind=BOT_ALLOWLIST):
    row = conn.execute(OPEN, (kind, channel_id, by, case_id)).fetchone()
    if row is None:
        return None

    guard_id = row[0]
    audit.record(
        conn, "channel_guard", guard_id, "opened", by,
        after={"kind": kind, "channel_id": channel_id},
    )
    return guard_id


def lift(conn, guard_id, by):
    row = conn.execute(LIFT, (by, guard_id)).fetchone()
    if row is None:
        return None

    audit.record(conn, "channel_guard", guard_id, "lifted", by,
                 before={"state": "live"}, after={"state": "lifted"})
    return row[0]


def allow(conn, guard_id, subject_id, by, label=None):
    row = conn.execute(ALLOW, (guard_id, subject_id, label, by)).fetchone()
    if row is None:
        return None

    audit.record(conn, "channel_allow", guard_id, "added", by,
                 after={"subject_id": subject_id, "label": label})
    return row[0]


def disallow(conn, guard_id, subject_id, by):
    row = conn.execute(DISALLOW, (guard_id, subject_id)).fetchone()
    if row is None:
        return None

    audit.record(conn, "channel_allow", guard_id, "removed", by,
                 before={"subject_id": subject_id}, after=None)
    return row[0]


def open_notice_thread(conn, guard_id, subject_id, idle_timeout, max_age):
    return conn.execute(
        OPEN_NOTICE_THREAD, (guard_id, subject_id, idle_timeout, max_age),
    ).fetchone()


def open_new_notice_thread(conn, guard_id, subject_id, parent_ts, deleted, kicked):
    return conn.execute(
        OPEN_NEW_NOTICE_THREAD, (guard_id, subject_id, parent_ts, deleted, kicked),
    ).fetchone()[0]


def add_notice_counts(conn, thread_id, deleted, kicked):
    return conn.execute(ADD_NOTICE_COUNTS, (deleted, kicked, thread_id)).fetchone()


def notice_groups(conn, give_up_after, limit):
    return conn.execute(NOTICE_GROUPS, (give_up_after, limit)).fetchall()


def claim_notices(conn, guard_id, subject_id, give_up_after, limit):
    rows = conn.execute(CLAIM_NOTICES, (guard_id, subject_id, give_up_after, limit)).fetchall()
    return [dict(zip(NOTICE_FIELDS, row)) for row in rows]


def mark_noticed(conn, event_ids):
    conn.execute(MARK_NOTICED, (list(event_ids),))


def notice_failed(conn, event_ids):
    return conn.execute(NOTICE_FAILED, (list(event_ids),)).fetchall()


def claim_removals(conn, limit):
    return conn.execute(CLAIM_REMOVALS, (limit,)).fetchall()


def clear_remove_pending(conn, event_id):
    conn.execute(CLEAR_REMOVE_PENDING, (event_id,))


def removal_failed(conn, event_id, why, give_up_after):
    return conn.execute(REMOVAL_FAILED, (why, give_up_after, give_up_after, event_id)).fetchone()[0]


TEXT_LIMIT = 8000


def record_enforcement(conn, guard_id, channel_id, subject_id, verb, bot_id=None, label=None, text=None,
             message_ts=None, permalink=None, app_id=None, detail=None, notice_wanted=False,
             remove_pending=False):
    return conn.execute(
        INSERT_EVENT,
        (guard_id, channel_id, subject_id, bot_id, label, verb,
         (text or None) and text[:TEXT_LIMIT],
         message_ts, permalink, app_id, detail, notice_wanted, remove_pending),
    ).fetchone()[0]
