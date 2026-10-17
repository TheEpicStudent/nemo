from bot.core.formatting import short_end
from bot.nemo.views import action, report

ROW_LIMIT = 8

COUNTS = """
SELECT
  (SELECT count(*) FROM fd.case_participants
   WHERE user_id = %(user_id)s AND role = 'subject') AS subject_case_count,
  (SELECT count(DISTINCT case_id) FROM fd.case_participants
   WHERE user_id = %(user_id)s) AS case_count,
  (SELECT count(*) FROM fd.member_guards
   WHERE subject_id = %(user_id)s AND state IN ('live', 'lifting')) AS active_guard_count,
  (SELECT count(*) FROM fd.actions
   WHERE target_user_id = %(user_id)s AND reversed_at IS NOT NULL) AS reversed_action_count
"""

IN_FORCE = """
SELECT kind, expires_at, channel_id, case_id, enforcement_status, enforced_by
FROM fd.member_guards
WHERE subject_id = %(user_id)s AND state IN ('live', 'lifting')
ORDER BY array_position(%(worst_first)s::text[], kind), opened_at DESC
LIMIT 1
"""

ENTRIES = """
WITH entries AS (
  SELECT c.opened_at AS at, 'cases' AS kind, c.id AS case_id,
         c.category_key AS type_key, c.resolution AS actor_or_resolution, NULL::text AS note
  FROM fd.cases c
  JOIN fd.case_participants p ON p.case_id = c.id AND p.role = 'subject'
  WHERE p.user_id = %(user_id)s

  UNION ALL
  SELECT a.performed_at, 'actions', a.case_id, a.type_key, a.performed_by, NULL::text
  FROM fd.actions a
  WHERE a.target_user_id = %(user_id)s

  UNION ALL
  SELECT a.reversed_at, 'reversed', a.case_id, a.type_key, a.reversed_by, a.reversal_reason
  FROM fd.actions a
  WHERE a.target_user_id = %(user_id)s AND a.reversed_at IS NOT NULL

  UNION ALL
  SELECT n.created_at, 'notes', NULL::bigint, NULL::text, n.author, n.body
  FROM fd.notes n
  WHERE n.subject_user_id = %(user_id)s AND n.deleted_at IS NULL
)
SELECT count(*) OVER () AS total, at, kind, case_id, type_key, actor_or_resolution, note
FROM entries
ORDER BY at DESC
LIMIT %(row_limit)s
"""


def worst_first():
    table = action.table()
    return sorted(table, key=lambda key: table[key]["weight"])


def read(conn, user_id, row_limit=ROW_LIMIT):
    counts = conn.execute(COUNTS, {"user_id": user_id}).fetchone()
    in_force_row = conn.execute(
        IN_FORCE, {"user_id": user_id, "worst_first": worst_first()}
    ).fetchone()
    entry_rows = conn.execute(ENTRIES, {"user_id": user_id, "row_limit": row_limit}).fetchall()

    return {
        "user_id": user_id,
        "counts": {
            "subject_case_count": counts[0],
            "case_count": counts[1],
            "active_guard_count": counts[2],
            "reversed_action_count": counts[3],
        },
        "in_force": (
            {
                "kind": in_force_row[0],
                "expires_at": in_force_row[1],
                "channel_id": in_force_row[2],
                "case_id": in_force_row[3],
                "enforcement_status": in_force_row[4],
                "enforced_by": in_force_row[5],
            }
            if in_force_row
            else None
        ),
        "total": entry_rows[0][0] if entry_rows else 0,
        "entries": [
            {
                "at": row[1],
                "kind": row[2],
                "case_id": row[3],
                "type_key": row[4],
                "actor_or_resolution": row[5],
                "note": row[6],
            }
            for row in entry_rows
        ],
    }


def format_date(at):
    return at.strftime("%-d %b %Y") if at else "n/a"


def format_counts(counts):
    parts = [
        f"{counts['subject_case_count']} as subject",
        f"{counts['case_count']} case{'' if counts['case_count'] == 1 else 's'}",
        f"{counts['active_guard_count']} active",
    ]
    if counts["reversed_action_count"]:
        parts.append(f"{counts['reversed_action_count']} reversed")
    return ", ".join(parts)


ENFORCEMENT_STATUS_LABELS = {
    "pending": "pending",
    "failed": "not enforced",
}


def in_force_line(guard):
    if guard is None:
        return "nothing active"

    text = action.label(guard["kind"]).lower()
    where = guard.get("channel_id")
    if where:
        text += f" in <#{where}>"
    if guard.get("expires_at"):
        text += f" until {short_end(guard['expires_at'])}"
    else:
        text += ", no end date"

    if guard.get("enforced_by") == "by_hand":
        return f"{text}, manual"
    status_label = ENFORCEMENT_STATUS_LABELS.get(guard.get("enforcement_status"))
    return f"{text}, {status_label}" if status_label else text


def entry_line(entry):
    at = format_date(entry["at"])
    if entry["kind"] == "cases":
        category = report.category_label(entry["type_key"]) or "not set"
        ending = f", {entry['actor_or_resolution'].replace('_', ' ')}" if entry["actor_or_resolution"] else ", open"
        return f"case {entry['case_id']}, {category.lower()}{ending} on {at}"

    if entry["kind"] == "actions":
        return (
            f"{action.label(entry['type_key']).lower()} on case {entry['case_id']} "
            f"by <@{entry['actor_or_resolution']}>, {at}"
        )

    if entry["kind"] == "reversed":
        text = (f"{action.label(entry['type_key']).lower()} on {at}, "
                f"reversed by <@{entry['actor_or_resolution']}>")
        return f"{text}, {entry['note']}" if entry["note"] else text

    return f"note by <@{entry['actor_or_resolution']}> on {at}: {entry['note']}"
