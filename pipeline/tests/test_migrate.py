import psycopg
import pytest

from jobs import migrate


class FakePath:
    name = "0099_test.sql"

    def read_text(self):
        return "ALTER TABLE raw.ingest_run ADD COLUMN x int"

    def read_bytes(self):
        return b"ALTER TABLE raw.ingest_run ADD COLUMN x int"


class LockedThenFree:
    def __init__(self, locked_for):
        self.locked_for = locked_for
        self.executed = []
        self.rollbacks = 0
        self.commits = 0

    def execute(self, sql, params=None):
        self.executed.append(sql)
        if sql.startswith("ALTER") and len([s for s in self.executed if s.startswith("ALTER")]) <= self.locked_for:
            raise psycopg.errors.LockNotAvailable("canceling statement due to lock timeout")
        return self

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1


def test_apply_lock_timeout_then_free_commits_after_one_rollback(monkeypatch):
    monkeypatch.setattr(migrate.time, "sleep", lambda s: None)
    conn = LockedThenFree(locked_for=1)
    migrate.apply(conn, FakePath(), attempts=3, wait=0)
    assert conn.rollbacks == 1
    assert conn.commits == 1
    assert any("schema_version" in s for s in conn.executed)


def test_apply_lock_never_free_exits_with_filename_and_attempts(monkeypatch):
    monkeypatch.setattr(migrate.time, "sleep", lambda s: None)
    conn = LockedThenFree(locked_for=99)
    with pytest.raises(SystemExit) as exit_error:
        migrate.apply(conn, FakePath(), attempts=3, wait=0)
    assert "0099_test.sql" in str(exit_error.value)
    assert "3 attempts" in str(exit_error.value)
    assert conn.rollbacks == 3
    assert conn.commits == 0


def test_apply_without_lock_contention_commits_once():
    conn = LockedThenFree(locked_for=0)
    migrate.apply(conn, FakePath())
    assert conn.rollbacks == 0
    assert conn.commits == 1


ALLOWED_DUPLICATE_NUMBERS = frozenset({"0140"})


def test_migrations_numbers_are_unique_except_allowed_duplicates():
    from collections import Counter

    from lib.paths import MIGRATIONS_DIR, MIGRATIONS_POST_DIR

    for folder in (MIGRATIONS_DIR, MIGRATIONS_POST_DIR):
        counts = Counter(path.name.split("_", 1)[0] for path in folder.glob("*.sql"))
        duplicates = sorted(
            number
            for number, count in counts.items()
            if count > 1 and number not in ALLOWED_DUPLICATE_NUMBERS
        )
        assert not duplicates, (
            f"{folder.name} reuses migration number(s) {duplicates}. The runner keys "
            "raw.schema_version on the filename, so a number cannot be reclaimed once "
            "applied: pick the next free number instead"
        )
