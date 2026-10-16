from datetime import timedelta

import psycopg

from lib import sources

ENGINE_SETTINGS_SQL = "SELECT source, name, value FROM app.engine_setting"

LAST_OK_SQL = """
SELECT max(finished_at)
FROM raw.ingest_run
WHERE status = 'ok' AND source = ANY(%s)
"""

ENGINE = "engine"
DEFAULTS = {"run_at": "03:00", "budget_minutes": "480", "reclaim_seconds": "900"}

PERIOD = {
    "daily": timedelta(hours=20),
    "weekly": timedelta(days=7),
    "monthly": timedelta(days=28),
}


UNREADABLE = object()
_warned = False


def read_settings(conn):
    global _warned
    try:
        with conn.cursor() as cur:
            cur.execute(ENGINE_SETTINGS_SQL)
            return {(source, name): val for source, name, val in cur.fetchall()}
    except psycopg.Error as exc:
        conn.rollback()
        if not _warned:
            print(f"settings: app.engine_setting is unreadable, running on file defaults, "
                  f"{type(exc).__name__}: {exc}")
            _warned = True
        return UNREADABLE


def value(conn, source, name, fallback):
    engine_settings = read_settings(conn)
    if engine_settings is UNREADABLE:
        return fallback
    return engine_settings.get((source, name), fallback)


def cadence(conn, key):
    return value(conn, key, "cadence", sources.field_of(key, "cadence"))


def enabled(conn, key):
    return value(conn, key, "enabled", "true") != "false"


def limit(conn, key, name):
    bounds = sources.limit(key, name)
    return sources.clamped(key, name, value(conn, key, name, bounds["default"]))


def run_at(conn):
    return value(conn, ENGINE, "run_at", DEFAULTS["run_at"])


def budget_minutes(conn):
    return int(value(conn, ENGINE, "budget_minutes", DEFAULTS["budget_minutes"]))


RETAIN_ALL = "keep"


def floor_days(key):
    floor = sources.prune_floor(key)
    if not floor:
        return None
    count, unit = floor.split()
    return int(count) * (30 if unit.startswith("month") else 1)


RECLAIM_FLOOR_SECONDS = 300
OFF = "off"


def reclaim_seconds(conn):
    configured = value(conn, ENGINE, "reclaim_seconds", DEFAULTS["reclaim_seconds"])
    if configured == OFF:
        return None
    if configured in (None, ""):
        configured = DEFAULTS["reclaim_seconds"]
    return max(int(configured), RECLAIM_FLOOR_SECONDS)


def retention_days(conn, key):
    configured = value(conn, key, "retention_days", RETAIN_ALL)
    if configured == RETAIN_ALL:
        return None

    floor = floor_days(key)
    days = int(configured)
    if floor and days < floor:
        raise ValueError(f"{key}: {days} days is under the {floor} day floor")
    return days


def last_ok(conn, key):
    with conn.cursor() as cur:
        cur.execute(LAST_OK_SQL, (list(sources.runs_as(key)),))
        return cur.fetchone()[0]


def skip_reason(conn, key, now):
    if not enabled(conn, key):
        return "paused"

    cadence_name = cadence(conn, key)
    if cadence_name not in PERIOD:
        return f"{cadence_name}, not scheduled"

    last_ok_at = last_ok(conn, key)
    if last_ok_at is None:
        return None

    due_at = last_ok_at + PERIOD[cadence_name]
    if now < due_at:
        return f"{cadence_name}, next due {due_at:%b %-d %H:%M}"

    return None
