from psycopg.types.json import Jsonb

from bot.core import audit
from bot.nemo import channelguards


class Conn:
    def __init__(self, rows=None, lists=None):
        self.rows = rows or {}
        self.lists = lists or {}
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        sql = self.executed[-1][0]
        for marker, row in self.rows.items():
            if marker in sql:
                return row
        return None

    def fetchall(self):
        sql = self.executed[-1][0]
        for marker, rows in self.lists.items():
            if marker in sql:
                return rows
        return []


def recorded(monkeypatch):
    calls = []
    monkeypatch.setattr(audit, "record", lambda conn, *args, **kwargs: calls.append((args, kwargs)))
    return calls


def test_open_guard_stores_settings_and_audits_them(monkeypatch):
    calls = recorded(monkeypatch)
    conn = Conn({"INSERT INTO fd.channel_guards": (5,)})

    guard_id = channelguards.open_guard(conn, "C1", "UMOD", kind=channelguards.ACCOUNT_AGE, settings={"min_age_days": 7})

    sql, args = conn.executed[0]
    assert guard_id == 5 and "settings" in sql
    assert args[:4] == (channelguards.ACCOUNT_AGE, "C1", "UMOD", None) and isinstance(args[4], Jsonb)
    assert calls[0][0][:4] == ("channel_guard", 5, "opened", "UMOD")
    assert calls[0][1]["after"] == {"kind": channelguards.ACCOUNT_AGE, "channel_id": "C1", "min_age_days": 7}


def test_open_guard_without_settings_stores_empty_object(monkeypatch):
    recorded(monkeypatch)
    conn = Conn({"INSERT INTO fd.channel_guards": (5,)})

    channelguards.open_guard(conn, "C1", "UMOD")

    assert conn.executed[0][1][4].obj == {}


def test_open_guard_when_live_returns_none_without_audit(monkeypatch):
    calls = recorded(monkeypatch)

    assert channelguards.open_guard(Conn(), "C1", "UMOD") is None
    assert calls == []


def test_tune_audits_before_and_after(monkeypatch):
    calls = recorded(monkeypatch)
    conn = Conn({"UPDATE fd.channel_guards": ({"threads": False}, {"threads": True})})

    assert channelguards.tune(conn, 5, {"threads": True}, "UMOD") == {"threads": True}

    assert calls[0][0][:4] == ("channel_guard", 5, "tuned", "UMOD")
    assert calls[0][1] == {"before": {"threads": False}, "after": {"threads": True}}


def test_tune_lifted_guard_returns_none_without_audit(monkeypatch):
    calls = recorded(monkeypatch)

    assert channelguards.tune(Conn(), 5, {"threads": True}, "UMOD") is None
    assert calls == []


def test_restore_allows_copies_latest_lifted_guard_and_audits_each(monkeypatch):
    calls = recorded(monkeypatch)
    conn = Conn({"state = 'lifted'": (3,)}, {"INSERT INTO fd.channel_guard_allows": [("UA", "Ann"), ("UB", None)]})

    assert channelguards.restore_allows(conn, 9, "C1", channelguards.READONLY, "UMOD") == ["UA", "UB"]

    assert conn.executed[1][1] == (9, 3)
    assert [one[1]["after"] for one in calls] == [
        {"subject_id": "UA", "label": "Ann", "restored_from_guard_id": 3},
        {"subject_id": "UB", "label": None, "restored_from_guard_id": 3},
    ]
    assert all(one[0][:3] == ("channel_allow", 9, "added") for one in calls)


def test_restore_allows_without_previous_guard_copies_nothing(monkeypatch):
    calls = recorded(monkeypatch)
    conn = Conn()

    assert channelguards.restore_allows(conn, 9, "C1", channelguards.READONLY, "UMOD") == []

    assert len(conn.executed) == 1 and calls == []


def test_live_guard_settings_reads_channel_wide_live_row():
    conn = Conn({"thread_ts = ''": (4, {"threads": True})})

    assert channelguards.live_guard_settings(conn, "C1", channelguards.READONLY) == (4, {"threads": True})
    assert conn.executed[0][1] == ("C1", channelguards.READONLY)
