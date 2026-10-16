def _upsert_newest(column):
    return f"""
INSERT INTO fd.member_seen AS target (user_id, {column})
SELECT user_id, at FROM unnest(%s::text[], %s::timestamptz[]) AS incoming(user_id, at)
WHERE NOT EXISTS (
    SELECT 1 FROM fd.member_seen existing
    WHERE existing.user_id = incoming.user_id AND existing.{column} >= incoming.at
)
ON CONFLICT (user_id) DO UPDATE SET {column} = EXCLUDED.{column}
WHERE target.{column} IS NULL OR target.{column} < EXCLUDED.{column}
"""


POSTED_SQL = _upsert_newest("last_post_at")
LOGGED_IN_SQL = _upsert_newest("last_login_at")


def latest(pairs):
    latest_by_user = {}
    for user_id, at in pairs:
        if user_id and at is not None and (user_id not in latest_by_user or at > latest_by_user[user_id]):
            latest_by_user[user_id] = at
    return sorted(latest_by_user.items())


def _write(cur, sql, pairs):
    rows = latest(pairs)
    if rows:
        cur.execute(sql, ([user_id for user_id, _ in rows], [at for _, at in rows]))


def posted(cur, pairs):
    _write(cur, POSTED_SQL, pairs)


def logged_in(cur, pairs):
    _write(cur, LOGGED_IN_SQL, pairs)
