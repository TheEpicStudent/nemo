READER = "reader"
WRITER = "writer"
NUMBERS = "numbers"
IMPORT = "import"
FIREHOSE = "firehose"

RAN = """
INSERT INTO fd.lyla_sync_status (name, ran_at, ok_at, error)
VALUES (%(name)s, now(), CASE WHEN %(ok)s THEN now() END, %(error)s)
ON CONFLICT (name) DO UPDATE
SET ran_at = now(),
    ok_at = CASE WHEN %(ok)s THEN now() ELSE fd.lyla_sync_status.ok_at END,
    error = %(error)s
"""

IMPORTED = "SELECT 1 FROM fd.lyla_sync_status WHERE name = %s AND ok_at IS NOT NULL"


def ran(conn, name, error=None, ok=None):
    ok = error is None if ok is None else ok
    conn.execute(RAN, {"name": name, "ok": ok, "error": str(error)[:500] if error else None})


def imported(conn):
    return conn.execute(IMPORTED, (IMPORT,)).fetchone() is not None
