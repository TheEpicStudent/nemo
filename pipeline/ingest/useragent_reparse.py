from lib import useragent
from lib.db import ingest_run

SOURCE = "useragent_reparse"
BATCH = 5000

UNPARSED_SQL = """
SELECT id, ua
FROM slack.user_agent
WHERE read_at IS NULL
ORDER BY id DESC
LIMIT %s
"""

UPDATE_PARSED_SQL = """
UPDATE slack.user_agent
SET app = coalesce(%s, app),
    os = coalesce(%s, os),
    read_at = now()
WHERE id = %s
"""


def reparse_batch(conn, batch=BATCH):
    rows = conn.execute(UNPARSED_SQL, (batch,)).fetchall()
    if not rows:
        return 0

    updates = []
    for agent_id, ua in rows:
        parsed = useragent.parse(ua)
        updates.append((parsed["ua_app"], parsed["ua_os"], agent_id))

    with conn.cursor() as cur:
        cur.executemany(UPDATE_PARSED_SQL, updates)
    conn.commit()
    return len(updates)


def run(conn):
    with ingest_run(conn, SOURCE) as counts:
        counts.rows_in = reparse_batch(conn)

    print(f"{SOURCE}: {counts.rows_in} agent string(s) read again")
    return counts.rows_in
