from contextlib import contextmanager

import pytest

from bot.nemo import guard_actions, guards
from bot.nemo.surface import Ctx, thread_lock
from bot.nemo.views import guard as card

CHANNEL_ID = "C0PRIVATE"
THREAD_TS = "1700000000.000100"
MODERATOR_ID = "UMODERATOR"
GUARD_ID = 5


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
        card.END: {card.END + "_date": {"selected_date": "2100-01-01"},
                   card.END + "_time": {"selected_time": "00:00"}},
    }}
    body = {"user": {"id": MODERATOR_ID}, "view": view}
    return Ctx(None, body, client, lambda **kwargs: None)


@pytest.fixture
def finish_calls(monkeypatch):
    calls = []
    monkeypatch.setattr(thread_lock, "session", fake_session)
    monkeypatch.setattr(guards, "open_guard", lambda *args, **kwargs: GUARD_ID)
    monkeypatch.setattr(guards, "refresh", lambda conn: 0)
    monkeypatch.setattr(guard_actions, "lock_notice",
                        lambda conn, expires_at, reason: {"text": "*Thread locked*"})
    monkeypatch.setattr(
        guards, "finish",
        lambda conn, guard_id, state, error=None, sha=None, by=None: calls.append((guard_id, state, error)),
    )
    return calls


def warn_raises(error_code):
    def warn(*args, **kwargs):
        raise SlackApiFailure(error_code)

    return warn


def test_submit_lock_warning_failure_marks_guard_failed(monkeypatch, finish_calls):
    monkeypatch.setattr(guards, "warn", warn_raises("not_in_channel"))

    assert thread_lock.submit_lock(lock_submission(SlackClient())) is None
    assert finish_calls == [(GUARD_ID, "failed", "warning not posted: not_in_channel")]


def test_submit_lock_warning_failure_posts_ephemeral_to_moderator(monkeypatch, finish_calls):
    monkeypatch.setattr(guards, "warn", warn_raises("is_archived"))
    client = SlackClient()

    thread_lock.submit_lock(lock_submission(client))

    assert client.ephemerals[0]["user"] == MODERATOR_ID
    assert client.ephemerals[0]["thread_ts"] == THREAD_TS
    assert "is_archived" in client.ephemerals[0]["text"]
    assert client.messages == []


def test_submit_lock_warning_failure_with_ephemeral_error_posts_dm(monkeypatch, finish_calls):
    monkeypatch.setattr(guards, "warn", warn_raises("not_in_channel"))
    client = SlackClient(ephemeral_error="not_in_channel")

    thread_lock.submit_lock(lock_submission(client))

    assert client.messages[0]["channel"] == MODERATOR_ID
    assert "/invite @nemo" in client.messages[0]["text"]


def test_submit_lock_warning_posted_returns_guard_id_without_finishing(monkeypatch, finish_calls):
    monkeypatch.setattr(guards, "warn", lambda *args, **kwargs: "1700000000.000200")
    client = SlackClient()

    assert thread_lock.submit_lock(lock_submission(client)) == GUARD_ID
    assert finish_calls == []
    assert client.ephemerals == []
    assert client.messages == []
