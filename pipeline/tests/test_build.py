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
        self.ran = []
        self.newest = newest
        self.broken = broken
        self.committed = False
        self.rolled_back = False

    def execute(self, sql, args=None):
        if self.broken:
            raise psycopg.errors.UndefinedTable('relation "raw.worker_build" does not exist')
        self.ran.append((sql, args))
        return self

    def fetchone(self):
        return self.newest

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True


def test_the_build_is_a_short_hash_of_the_running_source():
    assert len(build.fingerprint()) == 12
    assert int(build.fingerprint(), 16) >= 0
    assert build.fingerprint() == build.digest()


def test_a_changed_source_file_changes_the_build(tmp_path):
    root = tree(tmp_path, {"pipeline/lib/a.py": "x = 1\n", "db/migrations/0001_a.sql": "SELECT 1;\n"})
    before = build.digest(root)

    (root / "pipeline/lib/a.py").write_text("x = 2\n")

    assert build.digest(root) != before


def test_a_renamed_migration_changes_the_build(tmp_path):
    root = tree(tmp_path, {"db/migrations/0001_a.sql": "SELECT 1;\n"})
    before = build.digest(root)

    (root / "db/migrations/0001_a.sql").rename(root / "db/migrations/0002_a.sql")

    assert build.digest(root) != before


def test_tests_caches_the_venv_and_other_files_leave_the_build_alone(tmp_path):
    root = tree(tmp_path, {"pipeline/lib/a.py": "x = 1\n", "db/sources.yml": "a: 1\n"})
    before = build.digest(root)

    tree(root, {
        "pipeline/tests/test_a.py": "assert True\n",
        "pipeline/.venv/lib/site.py": "y = 1\n",
        "pipeline/lib/__pycache__/a.py": "z = 1\n",
        "pipeline/bot/manifests/nemo.yml": "name: nemo\n",
        "web/app/models/a.rb": "class A; end\n",
    })

    assert build.digest(root) == before


def test_a_beat_stamps_this_build_and_reads_the_newest(monkeypatch):
    monkeypatch.setattr(build, "fingerprint", lambda: "abc123abc123")
    conn = Conn(newest=("def456def456",))

    assert build.keep(conn, "audit_worker") == "def456def456"
    assert conn.ran[0] == (build.SEEN_SQL, ("abc123abc123",))
    assert conn.ran[1] == (build.STAMP_SQL, ("abc123abc123", "audit_worker"))
    assert conn.ran[2] == (build.NEWEST_SQL, {"fresh": build.FRESH_SECONDS, "one_off": "manual"})
    assert conn.committed


def test_a_database_without_the_build_table_leaves_the_newest_unknown():
    conn = Conn(broken=True)

    assert build.keep(conn, "audit_worker") is None
    assert conn.rolled_back


def test_only_running_deployed_workers_decide_the_newest_build():
    assert "h.beat_at >= now() - make_interval(secs => %(fresh)s)" in build.NEWEST_SQL
    assert "h.worker <> %(one_off)s" in build.NEWEST_SQL
    assert "ORDER BY b.first_seen_at DESC" in build.NEWEST_SQL
    assert build.FRESH_SECONDS == 300


def test_heartbeats_keep_a_build_and_builds_keep_when_they_were_first_seen():
    sql = (build.ROOT / "db" / "migrations" / "0210_worker_build.sql").read_text()

    assert "ADD COLUMN IF NOT EXISTS build text" in sql
    assert "first_seen_at timestamptz NOT NULL DEFAULT now()" in sql
