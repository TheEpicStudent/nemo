import hashlib
import os
import pathlib
from functools import cache

import psycopg

ROOT = pathlib.Path(__file__).resolve().parents[2]
SOURCES = {"pipeline": (".py",), "db": (".sql", ".yml")}
SKIPPED_DIRS = {"tests", "__pycache__"}
ACTIVE_WITHIN_SECONDS = 300
MANUAL_WORKER = "manual"

INSERT_BUILD_SQL = "INSERT INTO raw.worker_build (build) VALUES (%s) ON CONFLICT (build) DO NOTHING"

HEARTBEAT_BUILD_SQL = "UPDATE raw.worker_heartbeat SET build = %s WHERE worker = %s"

NEWEST_SQL = """
SELECT b.build
FROM raw.worker_heartbeat h
JOIN raw.worker_build b ON b.build = h.build
WHERE h.beat_at >= now() - make_interval(secs => %(active_within)s) AND h.worker <> %(manual_worker)s
ORDER BY b.first_seen_at DESC, b.build DESC
LIMIT 1
"""


def source_files(root=ROOT):
    for top, suffixes in SOURCES.items():
        for folder, folders, files in os.walk(root / top):
            folders[:] = sorted(one for one in folders if one not in SKIPPED_DIRS and not one.startswith("."))
            for name in sorted(files):
                if name.endswith(suffixes):
                    yield pathlib.Path(folder) / name


def digest(root=ROOT):
    sha = hashlib.sha256()
    for path in source_files(root):
        sha.update(path.relative_to(root).as_posix().encode())
        sha.update(path.read_bytes())
    return sha.hexdigest()[:12]


@cache
def fingerprint():
    return digest()


def record_build(conn, worker):
    try:
        conn.execute(INSERT_BUILD_SQL, (fingerprint(),))
        conn.execute(HEARTBEAT_BUILD_SQL, (fingerprint(), worker))
        newest = conn.execute(NEWEST_SQL, {"active_within": ACTIVE_WITHIN_SECONDS, "manual_worker": MANUAL_WORKER}).fetchone()
        conn.commit()
    except psycopg.Error:
        conn.rollback()
        return None
    return newest[0] if newest else None

