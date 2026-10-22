from psycopg.types.json import Jsonb

from bot.core import audit

LYLA = "lyla"
SOURCE_SETTING = "SELECT set_config('fd.sync_source', %s, true)"

MAP_DIGESTS = """
SELECT source_key, source_digest FROM fd.import_map WHERE source_app = %s AND source_table = %s
"""

MAP_ROW = """
SELECT entity_table, entity_id, source_digest FROM fd.import_map
WHERE source_app = %s AND source_table = %s AND source_key = %s
"""

MAP_KEYS_FOR_ENTITY = """
SELECT source_key FROM fd.import_map
WHERE source_app = %s AND source_table = %s AND entity_table = %s AND entity_id = %s
ORDER BY synced_at
"""

PUT_MAP = """
INSERT INTO fd.import_map
    (source_app, source_table, source_key, entity_table, entity_id, source_digest)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (source_app, source_table, source_key) DO UPDATE
SET entity_table = EXCLUDED.entity_table, entity_id = EXCLUDED.entity_id,
    source_digest = EXCLUDED.source_digest, synced_at = now()
"""

FORGET_MAP = """
DELETE FROM fd.import_map WHERE source_app = %s AND source_table = %s AND source_key = %s
"""

CASE_CHANGED = "SELECT pg_notify('fd_case_changed', %s)"

RECORD = """
INSERT INTO fd.audit
    (occurred_at, actor_user_id, actor_kind, entity_type, entity_id, verb, before, after,
     source_app, subject_user_id)
VALUES (coalesce(%s, now()), %s, 'import', %s, %s, %s, %s, %s, %s, %s)
"""


def as_lyla(conn):
    conn.execute(SOURCE_SETTING, (LYLA,))


def as_nemo(conn):
    conn.execute(SOURCE_SETTING, ("",))


def digests(conn, table, app=LYLA):
    return {key: digest for key, digest in conn.execute(MAP_DIGESTS, (app, table)).fetchall()}


def mapped(conn, table, key, app=LYLA):
    return conn.execute(MAP_ROW, (app, table, str(key))).fetchone()


def keys_for(conn, table, entity_table, entity_id, app=LYLA):
    return [row[0] for row in conn.execute(
        MAP_KEYS_FOR_ENTITY, (app, table, entity_table, entity_id)).fetchall()]


def put(conn, table, key, entity_table, entity_id, digest=None, app=LYLA):
    conn.execute(PUT_MAP, (app, table, str(key), entity_table, entity_id, digest))


def forget(conn, table, key, app=LYLA):
    conn.execute(FORGET_MAP, (app, table, str(key)))


def json(value):
    return Jsonb(value, dumps=audit.encode) if value else None


def record(conn, entity_type, entity_id, verb, actor, before=None, after=None, app=LYLA,
           subject_user_id=None, at=None):
    conn.execute(RECORD, (at, actor, entity_type, entity_id, verb, json(before), json(after),
                          app, subject_user_id))


def touch_case(conn, case_id):
    conn.execute(CASE_CHANGED, (str(case_id),))
