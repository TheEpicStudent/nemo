import threading

from bot.core import loops


class Note:
    def __init__(self, channel, payload):
        self.channel = channel
        self.payload = payload


class FakeConn:
    def __init__(self, notes):
        self.notes = notes
        self.listening = []
        self.autocommit = False

    def execute(self, sql):
        self.listening.append(sql)

    def notifies(self, stop_after=None, timeout=None):
        return iter(self.notes)

    def close(self):
        pass


def dispatched_payloads(monkeypatch, notes):
    monkeypatch.setattr(loops, "connect", lambda: FakeConn(notes))
    payloads = []
    loops.listen(
        "nemo", ("fd_channel_guard",), lambda name, payload: payloads.append((name, payload)),
        threading.Event(),
    )
    return payloads


def test_listen_channel_id_payload_is_dispatched_as_string(monkeypatch):
    payloads = dispatched_payloads(monkeypatch, [Note("fd_channel_guard", "C0BAHBV008Z")])
    assert payloads == [("fd_channel_guard", "C0BAHBV008Z")]


def test_listen_numeric_payload_is_dispatched_as_int(monkeypatch):
    payloads = dispatched_payloads(monkeypatch, [Note("fd_case_changed", "41")])
    assert payloads == [("fd_case_changed", 41)]


def test_listen_empty_payload_is_not_dispatched(monkeypatch):
    assert dispatched_payloads(monkeypatch, [Note("fd_channel_guard", "")]) == []
