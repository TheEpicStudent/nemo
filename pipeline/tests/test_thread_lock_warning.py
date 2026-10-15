from contextlib import contextmanager

import pytest

from bot.nemo import guards
from bot.nemo.surface import Ctx, thread_lock
from bot.nemo.views import guard as card

CHANNEL_ID = "C0PRIVATE"
THREAD_TS = "1700000000.000100"
MODERATOR_ID = "UMODERATOR"
GUARD_ID = 5
LOCK_UNTIL = 4102444800


class SlackApiFailure(Exception):
    def __init__(self, error_code):
        super().__init__(error_code)
        self.response = type("Response", (), {"data": {"error": error_code}})()


class SlackClient:
    def __init__(self, ephemeral_error=None):
        self.ephemeral_error = ephemeral_error
        self.ephemerals = []
        self.messages = []

    def conversations_join(self, **kwargs):
        return {"ok": True}

    def chat_postEphemeral(self, **kwargs):
        if self.ephemeral_error:
            raise SlackApiFailure(self.ephemeral_error)
        self.ephemerals.append(kwargs)

    def chat_postMessage(self, **kwargs):
        self.messages.append(kwargs)
        return {"ts": "1.1"}


@contextmanager
def fake_session():
    yield object()


def lock_submission(client):
    view = card.lock_view(CHANNEL_ID, THREAD_TS)
    view["state"] = {"values": {
        card.REASON: {card.REASON: {"value": "raid"}},
        card.UNTIL: {card.UNTIL: {"selected_date_time": LOCK_UNTIL}},
    }}
    body = {"user": {"id": MODERATOR_ID}, "view": view}
    return Ctx(None, body, client, lambda **kwargs: None)


@pytest.fixture
def finish_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(thread_lock, "session", fake_session)
    monkeypatch.setattr(guards, "open_guard", lambda *args, **kwargs: GUARD_ID)
    monkeypatch.setattr(guards, "refresh", lambda conn: 0)
    monkeypatch.setattr(
        guards, "finish",
        lambda conn, guard_id, state, error=None, sha=None: calls.append((guard_id, state, error)),
    )
    return calls


def warn_raises(error_code):
    def warn(*args, **kwargs):
        raise SlackApiFailure(error_code)

    return warn


def test_lock_warning_failure_fails_guard(monkeypatch, finish_calls):
    monkeypatch.setattr(guards, "warn", warn_raises("not_in_channel"))

    assert thread_lock.confirmed(lock_submission(SlackClient())) is None
    assert finish_calls == [(GUARD_ID, "failed", "warning not posted: not_in_channel")]


def test_lock_warning_failure_uses_ephemeral_when_allowed(monkeypatch, finish_calls):
    monkeypatch.setattr(guards, "warn", warn_raises("is_archived"))
    client = SlackClient()

    thread_lock.confirmed(lock_submission(client))

    assert client.ephemerals[0]["user"] == MODERATOR_ID
    assert client.ephemerals[0]["thread_ts"] == THREAD_TS
    assert "is_archived" in client.ephemerals[0]["text"]
    assert client.messages == []


def test_lock_warning_failure_falls_back_to_dm(monkeypatch, finish_calls):
    monkeypatch.setattr(guards, "warn", warn_raises("not_in_channel"))
    client = SlackClient(ephemeral_error="not_in_channel")

    thread_lock.confirmed(lock_submission(client))

    assert client.messages[0]["channel"] == MODERATOR_ID
    assert "/invite @nemo" in client.messages[0]["text"]


def test_lock_warning_posted_keeps_guard_live(monkeypatch, finish_calls):
    monkeypatch.setattr(guards, "warn", lambda *args, **kwargs: "1700000000.000200")
    client = SlackClient()

    assert thread_lock.confirmed(lock_submission(client)) == GUARD_ID
    assert finish_calls == []
    assert client.ephemerals == []
    assert client.messages == []
