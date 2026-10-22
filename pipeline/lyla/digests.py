ACTION = """
md5(concat_ws('|', x.case_number, x.action_type, x.target_user_id, x.performed_by::text,
              x.data::text, x.performed_at, x.category_code, x.category_extra))
"""

CASES_TEMPLATE = f"""
WITH threads AS (
    SELECT case_number,
           string_agg(concat_ws(':', channel, thread_ts, is_primary), ','
                      ORDER BY channel, thread_ts) AS rows
    FROM case_threads {{where}} GROUP BY case_number
), assignees AS (
    SELECT case_number,
           string_agg(concat_ws(':', user_id, assignment_source), ',' ORDER BY user_id) AS rows
    FROM case_assignees {{where}} GROUP BY case_number
), actions AS (
    SELECT x.case_number, string_agg({ACTION}, ',' ORDER BY x.id) AS rows
    FROM case_actions x {{where}} GROUP BY x.case_number
)
SELECT c.case_number,
       md5(concat_ws('|', c.status, c.created_at, c.resolved_at, c.resolved_by,
                     c.resolution_kind, c.merged_into, t.rows, a.rows, x.rows))
FROM cases c
LEFT JOIN threads t USING (case_number)
LEFT JOIN assignees a USING (case_number)
LEFT JOIN actions x USING (case_number)
{{where}}
"""

CASES = CASES_TEMPLATE.format(where="")

ONE_CASE = CASES_TEMPLATE.format(where="WHERE case_number = %(case_number)s")

ORPHAN_ACTIONS = f"""
SELECT x.id, {ACTION}
FROM case_actions x
WHERE NOT EXISTS (SELECT 1 FROM cases c WHERE c.case_number = x.case_number)
"""

NOTES = """
SELECT id, md5(concat_ws('|', target_user_id, body, created_by, created_at, edited_by, edited_at))
FROM user_notes
"""


def one_case(lyla, case_number):
    row = lyla.execute(ONE_CASE, {"case_number": case_number}).fetchone()
    return row[1] if row else None
