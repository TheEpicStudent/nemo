import contextlib
import types

import pytest

from lyla import status, sync, tasks


class Rows:
    def __init__(self, rows, rowcount=0):
        self.rows = rows
        self.rowcount = rowcount

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Conn:
    def __init__(self, link="on", imported=False, foreign=0):
        self.link = link
        self.imported = imported
        self.foreign = foreign
        self.ran = []
        self.cleared = False

    def execute(self, sql, args=None):
        if "fd.app_settings" in sql:
            return Rows([(self.link,)])
        if sql == status.IMPORTED:
            return Rows([(1,)] if self.imported else [])
        if sql == status.RAN:
            self.ran.append((args["name"], args["ok"], args["error"]))
            return Rows([])
        if sql == sync.FOREIGN_CASES:
            return Rows([(self.foreign,)])
        if sql == sync.CLEAR_OUTBOX:
            self.cleared = True
            return Rows([], rowcount=4)
        raise AssertionError(sql)


class Lyla:
    closed = False

    def execute(self, sql, args=None):
        return Rows([(5010,)])

    def rollback(self):
        pass


def reader_returning(summary=None, failure=None):
    class Reader:
        def __init__(self, session, lyla):
            pass

        def run(self):
            if failure:
                raise failure
            return summary or {}

    return Reader


@pytest.fixture
def worker(monkeypatch):
    def build(conn, reader=None):
        @contextlib.contextmanager
        def session():
            yield conn

        monkeypatch.setattr(sync, "session", session)
        monkeypatch.setattr(sync, "Reader", reader or reader_returning({"cases": 3}))
        monkeypatch.setattr(sync.categories, "mirror", lambda conn, lyla: [])
        monkeypatch.setattr(sync.numbers, "refill", lambda conn, lyla: None)
        one = sync.Sync()
        one.lyla = Lyla()
        monkeypatch.setattr(one, "write", lambda lyla: None)
        monkeypatch.setattr(one, "read", lambda lyla: None)
        return one

    return build


def test_link_off_does_not_touch_lyla(worker):
    one = worker(Conn(link="off"))
    one.lyla = None
    one.connection = lambda: pytest.fail("connected to LYLA")
    assert one.cycle() is False


def test_link_on_imports_first_then_syncs(worker):
    conn = Conn()
    assert worker(conn).cycle() is True
    assert conn.cleared
    assert conn.ran[:2] == [(status.IMPORT, False, None), (status.IMPORT, True, None)]


def test_import_with_failures_still_counts_as_imported(worker):
    conn = Conn()
    worker(conn, reader_returning({"failed": 2})).cycle()
    assert (status.IMPORT, True, "2 failed") in conn.ran


def test_import_refuses_while_nemo_cases_use_lyla_numbers(worker):
    conn = Conn(foreign=56)
    assert worker(conn).cycle() is False
    assert not conn.cleared
    assert conn.ran == [(status.IMPORT, False, "56 Nemo case(s) already use LYLA case numbers")]


def test_import_failure_is_recorded_and_raised(worker):
    conn = Conn()
    with pytest.raises(RuntimeError):
        worker(conn, reader_returning(failure=RuntimeError("LYLA went away"))).cycle()
    assert conn.ran[-1] == (status.IMPORT, False, "LYLA went away")


def test_after_the_import_the_cycle_skips_it(worker):
    conn = Conn(imported=True)
    assert worker(conn, reader_returning(failure=AssertionError("imported twice"))).cycle() is True
    assert not conn.cleared


def test_tasks_start_nothing_without_urls(monkeypatch):
    monkeypatch.delenv("LYLA_DATABASE_URL", raising=False)
    monkeypatch.delenv("FIREHOSE_DATABASE_URL", raising=False)
    assert tasks.start(None, None) == []


def test_tasks_start_each_loop_its_url_allows(monkeypatch):
    monkeypatch.setattr(tasks, "spawn", lambda name, target, *args: types.SimpleNamespace(name=name))
    monkeypatch.setenv("LYLA_DATABASE_URL", "postgresql://lyla")
    monkeypatch.delenv("FIREHOSE_DATABASE_URL", raising=False)
    assert [one.name for one in tasks.start(None, None)] == ["lyla-sync", "lyla-chat-import"]
    monkeypatch.setenv("FIREHOSE_DATABASE_URL", "postgresql://firehose")
    assert [one.name for one in tasks.start(None, None)] == ["lyla-sync", "lyla-chat-import",
                                                            "firehose-mirror"]
