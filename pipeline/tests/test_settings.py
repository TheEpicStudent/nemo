import psycopg

from lib import settings


class BrokenConn:
    def __init__(self):
        self.rollbacks = 0

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql):
        raise psycopg.errors.InsufficientPrivilege("permission denied for table engine_setting")

    def rollback(self):
        self.rollbacks += 1


class EmptyConn(BrokenConn):
    def execute(self, sql):
        return self

    def fetchall(self):
        return []


def test_read_settings_unreadable_table_returns_unreadable_sentinel(monkeypatch):
    monkeypatch.setattr(settings, "_warned", False)
    conn = BrokenConn()
    assert settings.read_settings(conn) is settings.UNREADABLE
    assert conn.rollbacks == 1


def test_read_settings_empty_table_returns_empty_dict():
    assert settings.read_settings(EmptyConn()) == {}


def test_value_unreadable_or_missing_setting_returns_fallback(monkeypatch):
    monkeypatch.setattr(settings, "_warned", False)
    assert settings.value(BrokenConn(), "member_days", "batch", "6") == "6"
    assert settings.value(EmptyConn(), "member_days", "batch", "6") == "6"


class TunedConn(EmptyConn):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows

    def fetchall(self):
        return self.rows


def test_reclaim_seconds_without_setting_returns_default():
    assert settings.reclaim_seconds(EmptyConn()) == 900


def test_reclaim_seconds_reads_setting_with_floor_and_blank_default():
    conn = TunedConn([("engine", "reclaim_seconds", "1800")])
    assert settings.reclaim_seconds(conn) == 1800

    low = TunedConn([("engine", "reclaim_seconds", "30")])
    assert settings.reclaim_seconds(low) == settings.RECLAIM_FLOOR_SECONDS

    blank = TunedConn([("engine", "reclaim_seconds", "")])
    assert settings.reclaim_seconds(blank) == 900


def test_reclaim_seconds_off_setting_returns_none():
    off = TunedConn([("engine", "reclaim_seconds", settings.OFF)])
    assert settings.reclaim_seconds(off) is None


def test_reclaim_seconds_unreadable_table_returns_default(monkeypatch):
    monkeypatch.setattr(settings, "_warned", False)
    assert settings.reclaim_seconds(BrokenConn()) == 900


def test_read_settings_unreadable_table_prints_warning_once(monkeypatch, capsys):
    monkeypatch.setattr(settings, "_warned", False)
    conn = BrokenConn()
    settings.read_settings(conn)
    settings.read_settings(conn)
    out = capsys.readouterr().out
    assert out.count("app.engine_setting is unreadable") == 1
