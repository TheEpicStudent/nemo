from bot.nemo.channel import app_url, case_url
from bot.nemo.views import open_cases as view
from bot.nemo.views.activity import message_url

CASE_LIMIT = 25
REPORTS_PER_CASE = 3
CASE_LIST_PATH = "/fd/cases?view=attention"

OPEN_CASE_COUNT = "SELECT count(*) FROM fd.cases WHERE resolved_at IS NULL"

OPEN_CASES = """
SELECT c.id, c.category_key, c.opened_at, c.card_channel_id, c.card_ts, c.card_thread_ts,
       ARRAY(SELECT a.user_id FROM fd.case_assignees a
             WHERE a.case_id = c.id ORDER BY a.assigned_at, a.user_id)
FROM fd.cases c
WHERE c.resolved_at IS NULL
ORDER BY c.opened_at, c.id
LIMIT %s
"""

CASE_REPORTS = """
SELECT case_id, body, card_channel_id, forwarded_ts FROM (
    SELECT r.case_id, r.body, r.card_channel_id, r.forwarded_ts,
           row_number() OVER (PARTITION BY r.case_id ORDER BY r.received_at, r.id) AS report_index
    FROM fd.case_reports r
    WHERE r.case_id = ANY(%s)
) indexed_reports
WHERE report_index <= %s
ORDER BY case_id, report_index
"""

CARD_OPENING_BODIES = """
SELECT DISTINCT ON (case_id) case_id, body FROM fd.case_chat
WHERE case_id = ANY(%s) AND mirrored_as = 'card' AND deleted_at IS NULL
ORDER BY case_id, id
"""

MEMBER_NAMES = """
SELECT user_id, coalesce(nullif(display_name, ''), handle) FROM fd.member
WHERE user_id = ANY(%s)
"""

CHANNEL_NAMES = "SELECT channel_id, name FROM raw.channel_dim WHERE channel_id = ANY(%s)"


def link_entry(body, channel_id, ts, thread_ts=None):
    return {"body": body, "url": message_url(channel_id, ts, thread_ts) if channel_id and ts else None}


def fetch_open_cases(conn, limit=CASE_LIMIT):
    total = conn.execute(OPEN_CASE_COUNT).fetchone()[0]
    rows = conn.execute(OPEN_CASES, (limit,)).fetchall()
    case_ids = [row[0] for row in rows]

    reports_by_case = {}
    for case_id, body, channel_id, ts in conn.execute(CASE_REPORTS, (case_ids, REPORTS_PER_CASE)).fetchall():
        reports_by_case.setdefault(case_id, []).append(link_entry(body, channel_id, ts))
    opening_bodies = dict(conn.execute(CARD_OPENING_BODIES, (case_ids,)).fetchall()) if case_ids else {}

    cases = []
    for case_id, category_key, opened_at, card_channel_id, card_ts, card_thread_ts, assignees in rows:
        entries = reports_by_case.get(case_id)
        if not entries and card_ts:
            entries = [link_entry(opening_bodies.get(case_id), card_channel_id, card_ts, card_thread_ts)]
        cases.append({"case_id": case_id, "category_key": category_key, "opened_at": opened_at,
                      "assignees": list(assignees or []), "url": case_url(case_id),
                      "entries": entries or [], "has_reports": case_id in reports_by_case})
    return total, cases


def resolve_mention_names(conn, cases):
    bodies = [entry["body"] for case in cases for entry in case["entries"]]
    user_ids, channel_ids = view.mention_ids(bodies)
    names = {}
    if user_ids:
        names.update((user_id, name) for user_id, name in conn.execute(MEMBER_NAMES, (user_ids,)).fetchall() if name)
    if channel_ids:
        names.update((channel_id, name) for channel_id, name in conn.execute(CHANNEL_NAMES, (channel_ids,)).fetchall()
                     if name)
    return names


def build_reply(conn, now=None):
    total, cases = fetch_open_cases(conn)
    return view.build_message(total, cases, resolve_mention_names(conn, cases), now=now,
                              list_url=app_url(CASE_LIST_PATH))
