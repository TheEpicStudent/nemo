STAFF = "case.read"

EXEMPT = """
SELECT coalesce(bool_or(m.is_admin OR m.is_owner OR m.is_org_admin OR m.is_org_owner), false)
       OR app.holds_capability(%s, %s)
FROM fd.member m
WHERE m.user_id = %s
"""


def is_exempt(conn, user_id):
    if not user_id:
        return False
    return bool(conn.execute(EXEMPT, (user_id, STAFF, user_id)).fetchone()[0])
