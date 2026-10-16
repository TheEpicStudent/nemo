from contextlib import contextmanager
from types import SimpleNamespace

from bot.nemo.surface import channel_watch


def capture(monkeypatch):
    recorded = []

    @contextmanager
    def session():
        yield "conn"

    monkeypatch.setattr(channel_watch, "session", session)
    monkeypatch.setattr(channel_watch.channel_dim, "record",
                        lambda conn, channel_id, **fields: recorded.append((channel_id, fields)))
    return recorded


def test_record_channel_renamed_with_name_records_new_name(monkeypatch):
    recorded = capture(monkeypatch)
    ctx = SimpleNamespace(payload={"type": "channel_rename", "channel": {"id": "C1", "name": "lounge"}})

    assert channel_watch.record_channel_renamed(ctx) == "C1"
    assert recorded == [("C1", {"name": "lounge"})]


def test_record_channel_renamed_without_name_returns_none(monkeypatch):
    recorded = capture(monkeypatch)

    assert channel_watch.record_channel_renamed(SimpleNamespace(payload={"channel": {"id": "C1"}})) is None
    assert channel_watch.record_channel_renamed(SimpleNamespace(payload={"channel": "C1"})) is None
    assert recorded == []
