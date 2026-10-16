import psycopg

from lib import build


def tree(root, files):
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return root


class Conn:
    def __init__(self, newest=None, broken=False):
        self.executed = []
        self.newest = newest
        self.broken = broken
        self.committed = False
        self.rolled_back = False

    def execute(self, sql, args=None):
        if self.broken:
            raise psycopg.errors.UndefinedTable('relation "raw.worker_build" does not exist')
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        return self.newest

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_fingerprint_returns_12_char_hex_digest():
    assert len(build.fingerprint()) == 12
    assert int(build.fingerprint(), 16) >= 0
    assert build.fingerprint() == build.digest()


def test_digest_changes_when_source_file_changes(tmp_path):
    root = tree(tmp_path, {"pipeline/lib/a.py": "x = 1\n", "db/migrations/0001_a.sql": "SELECT 1;\n"})
    original_digest = build.digest(root)

    (root / "pipeline/lib/a.py").write_text("x = 2\n")

    assert build.digest(root) != original_digest


def test_digest_changes_when_migration_is_renamed(tmp_path):
    root = tree(tmp_path, {"db/migrations/0001_a.sql": "SELECT 1;\n"})
    original_digest = build.digest(root)

    (root / "db/migrations/0001_a.sql").rename(root / "db/migrations/0002_a.sql")

    assert build.digest(root) != original_digest


def test_digest_ignores_tests_venv_pycache_and_non_source_files(tmp_path):
    root = tree(tmp_path, {"pipeline/lib/a.py": "x = 1\n", "db/sources.yml": "a: 1\n"})
    original_digest = build.digest(root)

    tree(root, {
        "pipeline/tests/test_a.py": "assert True\n",
        "pipeline/.venv/lib/site.py": "y = 1\n",
        "pipeline/lib/__pycache__/a.py": "z = 1\n",
        "pipeline/bot/manifests/nemo.yml": "name: nemo\n",
        "web/app/models/a.rb": "class A; end\n",
    })

    assert build.digest(root) == original_digest


def test_record_build_inserts_build_heartbeats_and_returns_newest(monkeypatch):
    monkeypatch.setattr(build, "fingerprint", lambda: "abc123abc123")
    conn = Conn(newest=("def456def456",))

    assert build.record_build(conn, "audit_worker") == "def456def456"
    assert conn.executed[0] == (build.INSERT_BUILD_SQL, ("abc123abc123",))
    assert conn.executed[1] == (build.HEARTBEAT_BUILD_SQL, ("abc123abc123", "audit_worker"))
    assert conn.executed[2] == (build.NEWEST_SQL, {"active_within": build.ACTIVE_WITHIN_SECONDS, "manual_worker": "manual"})
    assert conn.committed


def test_record_build_without_build_table_returns_none():
    conn = Conn(broken=True)

    assert build.record_build(conn, "audit_worker") is None
    assert conn.rolled_back


def test_newest_sql_filters_active_non_manual_workers():
    assert "h.beat_at >= now() - make_interval(secs => %(active_within)s)" in build.NEWEST_SQL
    assert "h.worker <> %(manual_worker)s" in build.NEWEST_SQL
    assert "ORDER BY b.first_seen_at DESC" in build.NEWEST_SQL
    assert build.ACTIVE_WITHIN_SECONDS == 300


def test_worker_build_migration_adds_build_and_first_seen_at_columns():
    sql = (build.ROOT / "db" / "migrations" / "0210_worker_build.sql").read_text()

    assert "ADD COLUMN IF NOT EXISTS build text" in sql
    assert "first_seen_at timestamptz NOT NULL DEFAULT now()" in sql
