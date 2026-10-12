import logging

from bot.nemo import channel
from bot.nemo.views import lines

log = logging.getLogger("bot.nemo")

CURSOR_NAME = "fire_engine_audit"
BATCH = 200
NOTE_LIMIT = 2900

CURSOR = "SELECT last_id FROM fd.bot_cursor WHERE name = %s FOR UPDATE SKIP LOCKED"

ADVANCE_CURSOR = "UPDATE fd.bot_cursor SET last_id = %s WHERE name = %s"

ENTRIES = """
SELECT id, actor_user_id, entity_type, entity_id, verb, before, after, request_id
FROM fd.audit
WHERE id > %s AND source_app = 'fire_engine'
  AND ((entity_type = 'assignee' AND verb IN ('attached', 'detached', 'claimed', 'unclaimed'))
       OR (entity_type = 'note' AND verb = 'noted')
       OR (entity_type = 'case' AND verb IN ('reopened', 'resolved')))
ORDER BY id
LIMIT %s
"""

NOTE = "SELECT case_id, body FROM fd.notes WHERE id = %s AND deleted_at IS NULL"


def user_of(payload):
    return (payload or {}).get("user_id")


def grouped(rows, key):
    groups = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    return groups


def announcement_lines(conn, rows):
    out = []
    by_request = grouped(rows, lambda row: (row[7] or f"row-{row[0]}", row[2], row[4], row[1]))
    for (_, entity, verb, actor), group in by_request.items():
        first = group[0]
        if entity == "assignee" and verb == "claimed":
            out.append((first[3], lines.claimed(actor, first[3])))
        elif entity == "assignee" and verb == "attached":
            for case_id, rows_here in grouped(group, lambda row: row[3]).items():
                users = [user_of(row[6]) for row in rows_here if user_of(row[6])]
                out += [(case_id, text) for text in lines.assigned(actor, case_id, users)]
        elif entity == "assignee" and verb in ("detached", "unclaimed"):
            for case_id, rows_here in grouped(group, lambda row: row[3]).items():
                users = [user_of(row[5]) or actor for row in rows_here]
                out.append((case_id, lines.unassigned(actor, case_id, users)))
        elif entity == "note":
            for row in group:
                note = conn.execute(NOTE, (row[3],)).fetchone()
                if note and note[0]:
                    out.append((note[0], lines.note_added(actor, note[1][:NOTE_LIMIT])))
        elif entity == "case" and verb == "reopened":
            out += [(row[3], lines.reopened(actor, row[3])) for row in group]
        elif entity == "case" and verb == "resolved":
            out += merges(actor, group)
    return out


def merges(actor, rows):
    into = {}
    for row in rows:
        after = row[6] or {}
        if after.get("resolution") == "duplicate" and after.get("duplicate_of"):
            into.setdefault(int(after["duplicate_of"]), []).append(row[3])
    out = []
    for primary_id, duplicate_ids in into.items():
        text = lines.merged(actor, sorted(duplicate_ids), primary_id, channel.case_url)
        out += [(case_id, text) for case_id in (primary_id, *sorted(duplicate_ids))]
    return out


def announce(client, conn):
    row = conn.execute(CURSOR, (CURSOR_NAME,)).fetchone()
    if row is None:
        return 0
    rows = conn.execute(ENTRIES, (row[0], BATCH)).fetchall()
    if not rows:
        return 0
    posted = 0
    for case_id, text in announcement_lines(conn, rows):
        if channel.post_line(client, conn, case_id, text):
            posted += 1
    conn.execute(ADVANCE_CURSOR, (rows[-1][0], CURSOR_NAME))
    if posted:
        log.info("nemo: %s fire engine change(s) told to their threads", posted)
    return posted
