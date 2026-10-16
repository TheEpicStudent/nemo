from bot.nemo.channel import app_url, case_url
from bot.nemo.views import open_cases as view
from bot.nemo.views.activity import message_url

LIMIT = 25
REPORTS_PER_CASE = 3
LIST_PATH = "/fd/cases?view=attention"

OPEN_COUNT = "SELECT count(*) FROM fd.cases WHERE resolved_at IS NULL"

OPEN_CASES = """
SELECT c.id, c.category_key, c.opened_at, c.card_channel_id, c.card_ts, c.card_thread_ts,
       ARRAY(SELECT a.user_id FROM fd.case_assignees a
             WHERE a.case_id = c.id ORDER BY a.assigned_at, a.user_id)
FROM fd.cases c
WHERE c.resolved_at IS NULL
ORDER BY c.opened_at, c.id
LIMIT %s
"""

REPORTS = """
SELECT case_id, body, card_channel_id, forwarded_ts FROM (
    SELECT r.case_id, r.body, r.card_channel_id, r.forwarded_ts,
           row_number() OVER (PARTITION BY r.case_id ORDER BY r.received_at, r.id) AS n
    FROM fd.case_reports r
    WHERE r.case_id = ANY(%s)
) ranked
WHERE n <= %s
ORDER BY case_id, n
"""

OPENINGS = """
SELECT DISTINCT ON (case_id) case_id, body FROM fd.case_chat
WHERE case_id = ANY(%s) AND mirrored_as = 'card' AND deleted_at IS NULL
ORDER BY case_id, id
"""

MEMBER_NAMES = """
SELECT user_id, coalesce(nullif(display_name, ''), handle) FROM fd.member
WHERE user_id = ANY(%s)
"""

CHANNEL_NAMES = "SELECT channel_id, name FROM raw.channel_dim WHERE channel_id = ANY(%s)"


def entry(body, channel_id, ts, thread_ts=None):
    return {"body": body, "url": message_url(channel_id, ts, thread_ts) if channel_id and ts else None}


def gather(conn, limit=LIMIT):
    total = conn.execute(OPEN_COUNT).fetchone()[0]
    rows = conn.execute(OPEN_CASES, (limit,)).fetchall()
    case_ids = [row[0] for row in rows]

    reports = {}
    for case_id, body, channel_id, ts in conn.execute(REPORTS, (case_ids, REPORTS_PER_CASE)).fetchall():
        reports.setdefault(case_id, []).append(entry(body, channel_id, ts))
    openings = dict(conn.execute(OPENINGS, (case_ids,)).fetchall()) if case_ids else {}

    cases = []
    for case_id, category_key, opened_at, card_channel_id, card_ts, card_thread_ts, assignees in rows:
        entries = reports.get(case_id)
        if not entries and card_ts:
            entries = [entry(openings.get(case_id), card_channel_id, card_ts, card_thread_ts)]
        cases.append({"case_id": case_id, "category_key": category_key, "opened_at": opened_at,
                      "assignees": list(assignees or []), "url": case_url(case_id),
                      "entries": entries or [], "is_report": bool(reports.get(case_id))})
    return total, cases


def names_for(conn, cases):
    bodies = [one["body"] for case in cases for one in case["entries"]]
    user_ids, channel_ids = view.mentioned(bodies)
    names = {}
    if user_ids:
        names.update((user_id, name) for user_id, name in conn.execute(MEMBER_NAMES, (user_ids,)).fetchall() if name)
    if channel_ids:
        names.update((channel_id, name) for channel_id, name in conn.execute(CHANNEL_NAMES, (channel_ids,)).fetchall()
                     if name)
    return names


def answer(conn, now=None):
    total, cases = gather(conn)
    return view.build(total, cases, names_for(conn, cases), now=now, list_url=app_url(LIST_PATH))
