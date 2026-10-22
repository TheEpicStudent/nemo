import contextlib
import datetime as dt
import threading

import pytest

from jobs import firehose_import

NOW = dt.datetime(2026, 10, 22, 12, tzinfo=dt.UTC)


class Firehose:
    def __init__(self, shushes, bans):
        self.results = {firehose_import.FIREHOSE_SHUSHES: shushes,
                        firehose_import.FIREHOSE_CHANNEL_BANS: bans}

    def execute(self, sql, args=None):
        return Rows(self.results[sql])

    def commit(self):
        return None


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


def test_live_rows_skip_ended_and_incomplete_rows_and_group_by_member():
    later = dt.datetime(2026, 11, 1)
    firehose = Firehose(
        [(1, "UONE", None, "spam", "UMOD", None), (2, "UTWO", None, "old", "UMOD", dt.datetime(2026, 10, 1)),
         (3, None, None, "no one", "UMOD", None)],
        [(4, "UTHREE", "C0GEN", "off topic", "UMOD", None), (5, "UTHREE", "C0GEN", "again", "UMOD2", later),
         (6, "UFOUR", None, "no channel", "UMOD", None)],
    )
    grouped = firehose_import.live_rows(firehose, now=NOW)
    assert set(grouped) == {firehose_import.Key("shush", "UONE", None),
                            firehose_import.Key("channel_ban", "UTHREE", "C0GEN")}
    assert [row["id"] for row in grouped[firehose_import.Key("channel_ban", "UTHREE", "C0GEN")]] == [4, 5]


def test_wanted_takes_no_end_over_any_end_and_the_first_reason():
    rows = [{"reason": " ", "admin": None, "expires_at": NOW},
            {"reason": "off topic", "admin": "UMOD", "expires_at": None}]
    assert firehose_import.wanted(rows) == (None, "off topic", "UMOD")


def test_wanted_takes_the_latest_end_and_defaults():
    later = NOW + dt.timedelta(days=3)
    rows = [{"reason": None, "admin": None, "expires_at": NOW},
            {"reason": "", "admin": None, "expires_at": later}]
    assert firehose_import.wanted(rows) == (later, "Firehose", "firehose")


def test_serve_with_the_link_off_does_not_read_firehose(monkeypatch):
    class Conn:
        def execute(self, sql, args=None):
            return self

        def fetchone(self):
            return ("off",)

    @contextlib.contextmanager
    def session():
        yield Conn()

    stopping = threading.Event()
    monkeypatch.setattr(firehose_import, "session", session)
    monkeypatch.setattr(firehose_import, "connect", lambda: pytest.fail("read Firehose"))
    monkeypatch.setattr(stopping, "wait", lambda seconds: stopping.set())
    firehose_import.serve(stopping)
