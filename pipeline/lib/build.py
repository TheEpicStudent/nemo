import hashlib
import os
import pathlib
from functools import cache

import psycopg

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCES = {"pipeline": (".py",), "db": (".sql", ".yml")}
SKIPPED = {"tests", "__pycache__"}
FRESH_SECONDS = 300
ONE_OFF = "manual"

SEEN_SQL = "INSERT INTO raw.worker_build (build) VALUES (%s) ON CONFLICT (build) DO NOTHING"

STAMP_SQL = "UPDATE raw.worker_heartbeat SET build = %s WHERE worker = %s"

NEWEST_SQL = """
SELECT b.build
FROM raw.worker_heartbeat h
JOIN raw.worker_build b ON b.build = h.build
WHERE h.beat_at >= now() - make_interval(secs => %(fresh)s) AND h.worker <> %(one_off)s
ORDER BY b.first_seen_at DESC, b.build DESC
LIMIT 1
"""


def sources(root=ROOT):
    for top, suffixes in SOURCES.items():
        for folder, folders, files in os.walk(root / top):
            folders[:] = sorted(one for one in folders if one not in SKIPPED and not one.startswith("."))
            for name in sorted(files):
                if name.endswith(suffixes):
                    yield pathlib.Path(folder) / name


def digest(root=ROOT):
    hashed = hashlib.sha256()
    for path in sources(root):
        hashed.update(path.relative_to(root).as_posix().encode())
        hashed.update(path.read_bytes())
    return hashed.hexdigest()[:12]


@cache
def fingerprint():
    return digest()


def keep(conn, worker):
    try:
        conn.execute(SEEN_SQL, (fingerprint(),))
        conn.execute(STAMP_SQL, (fingerprint(), worker))
        newest = conn.execute(NEWEST_SQL, {"fresh": FRESH_SECONDS, "one_off": ONE_OFF}).fetchone()
        conn.commit()
    except psycopg.Error:
        conn.rollback()
        return None
    return newest[0] if newest else None

