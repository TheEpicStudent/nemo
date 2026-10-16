import contextlib

import pytest

from bot.core import privileged


class Conn:
    def __init__(self, settings=None):
        self.settings = settings or {}
        self.keys = []
        self.key = None

    def execute(self, sql, args=None):
        assert sql == privileged.SETTING
        self.key = args[0]
        self.keys.append(self.key)
        return self

    def fetchone(self):
        return (self.settings[self.key],) if self.key in self.settings else None


def no_proxy(monkeypatch):
    def proxy():
        raise AssertionError("the proxy is not called")
    monkeypatch.setattr(privileged, "proxy", proxy)


@pytest.mark.parametrize(("stored", "expected"), [
    ("on", privileged.ON),
    (" OFF ", privileged.OFF),
    ("log", privileged.LOG),
    ("sometimes", privileged.LOG),
    (None, privileged.LOG),
])
def test_mode_session_reset_setting_value_maps_to_mode(stored, expected):
    conn = Conn({} if stored is None else {privileged.SESSION_RESET_SETTING: stored})

    assert privileged.mode(conn) == expected
    assert conn.keys == [privileged.SESSION_RESET_SETTING]


@pytest.mark.parametrize(("stored", "expected"), [
    ("on", privileged.ON),
    ("off", privileged.OFF),
    (None, privileged.LOG),
])
def test_deactivation_mode_deactivate_setting_value_maps_to_mode(stored, expected):
    conn = Conn({} if stored is None else {privileged.DEACTIVATE_SETTING: stored})

    assert privileged.deactivation_mode(conn) == expected
    assert conn.keys == [privileged.DEACTIVATE_SETTING]


@pytest.mark.parametrize(("stored", "expected"), [
    (None, privileged.DEFAULT_STRIKES),
    ("4", 4),
    ("0", 1),
    ("many", privileged.DEFAULT_STRIKES),
])
def test_strikes_needed_setting_value_floors_at_one_and_defaults_when_invalid(stored, expected):
    conn = Conn({} if stored is None else {privileged.STRIKES_SETTING: stored})

    assert privileged.strikes_needed(conn) == expected


@pytest.mark.parametrize(("stored", "expected"), [
    (None, privileged.DEFAULT_CAP),
    ("0", 0),
    ("-3", 0),
    ("12", 12),
])
def test_cap_per_guard_setting_value_floors_at_zero(stored, expected):
    conn = Conn({} if stored is None else {privileged.CAP_SETTING: stored})

    assert privileged.cap_per_guard(conn) == expected


@pytest.mark.parametrize(("stored", "outcome"), [("off", "off"), ("log", "would")])
def test_reset_sessions_off_or_log_mode_does_not_call_proxy(monkeypatch, stored, outcome):
    no_proxy(monkeypatch)

    assert privileged.reset_sessions("USUB", Conn({privileged.SESSION_RESET_SETTING: stored})) == outcome


@pytest.mark.parametrize(("stored", "outcome"), [("off", "off"), ("log", "would")])
def test_deactivate_and_reactivate_off_or_log_mode_do_not_call_proxy(monkeypatch, stored, outcome):
    no_proxy(monkeypatch)
    conn = Conn({privileged.DEACTIVATE_SETTING: stored})

    assert privileged.deactivate("USUB", conn) == outcome
    assert privileged.reactivate("USUB", conn) == outcome


def test_deactivate_on_mode_calls_proxy_with_deactivate_method(monkeypatch):
    calls = []

    class Proxy:
        def call(self, method, params, **options):
            calls.append((method, params, options["credential"]))

    monkeypatch.setattr(privileged, "proxy", Proxy)

    outcome = privileged.deactivate("USUB", Conn({privileged.DEACTIVATE_SETTING: "on"}))

    assert outcome == privileged.DEACTIVATED
    assert calls == [(privileged.DEACTIVATE, {"user_id": "USUB"}, "admin")]


def test_mode_without_conn_opens_session(monkeypatch):
    conn = Conn({privileged.SESSION_RESET_SETTING: "on"})

    @contextlib.contextmanager
    def session_of():
        yield conn

    monkeypatch.setattr(privileged, "session", session_of)

    assert privileged.mode() == privileged.ON
    assert conn.keys == [privileged.SESSION_RESET_SETTING]
