import contextlib

import pytest

from bot.nemo import userbots
from bot.nemo.surface import thread_watch

USER_ID = "U1"
CHANNEL_ID = "C1"
THREAD = "1700000000.000000"
TS = "1700000000.000100"
GUARD = (7, "lock", CHANNEL_ID, THREAD, "warned", "UMOD", "1700000000.000050", None)


class Slack:
    def __init__(self, users=None):
        self.users = users or {}

    def users_info(self, user):
        if user not in self.users:
            raise RuntimeError("user_not_found")
        return {"user": self.users[user]}


class Ctx:
    def __init__(self, event, client):
        self.payload = event
        self.client = client


@contextlib.contextmanager
def session_of():
    yield object()


def reply(**over):
    return {"user": USER_ID, "channel": CHANNEL_ID, "ts": TS, "thread_ts": THREAD, **over}


@pytest.fixture
def recorded_authors(monkeypatch):
    calls = []
    monkeypatch.setattr(userbots, "_users", {})
    monkeypatch.setattr(thread_watch, "session", session_of)
    monkeypatch.setattr(thread_watch.guards, "is_watched", lambda channel_id, ts: True)
    monkeypatch.setattr(thread_watch.guards, "active_guard", lambda conn, channel_id, ts: GUARD)
    monkeypatch.setattr(thread_watch.guards, "exempt", lambda conn, who, by: False)
    monkeypatch.setattr(thread_watch.guard_actions, "record_guarded_message",
                        lambda conn, guard, who, ts: calls.append(who) or True)
    monkeypatch.setattr(thread_watch.guard_actions, "delete_guarded_message",
                        lambda client, guard_id, channel_id, ts: True)
    monkeypatch.setattr(thread_watch.guard_actions, "record_and_escalate", lambda guard, who: None)
    return calls


def test_delete_guarded_thread_message_user_token_reply_is_recorded(recorded_authors):
    client = Slack(users={USER_ID: {"is_bot": False}})

    assert thread_watch.delete_guarded_thread_message(Ctx(reply(bot_id="B1"), client)) == "noted"
    assert recorded_authors == [USER_ID]


def test_delete_guarded_thread_message_bot_user_reply_returns_none(recorded_authors):
    client = Slack(users={USER_ID: {"is_bot": True}})

    assert thread_watch.delete_guarded_thread_message(Ctx(reply(bot_id="B1"), client)) is None
    assert recorded_authors == []


def test_delete_guarded_thread_message_plain_reply_is_recorded(recorded_authors):
    assert thread_watch.delete_guarded_thread_message(Ctx(reply(), Slack())) == "noted"
    assert recorded_authors == [USER_ID]
