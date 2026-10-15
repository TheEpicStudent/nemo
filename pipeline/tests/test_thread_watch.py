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
def noted(monkeypatch):
    calls = []
    monkeypatch.setattr(userbots, "_people", {})
    monkeypatch.setattr(thread_watch, "session", session_of)
    monkeypatch.setattr(thread_watch.guards, "watching", lambda channel_id, ts: True)
    monkeypatch.setattr(thread_watch.guards, "active_guard", lambda conn, channel_id, ts: GUARD)
    monkeypatch.setattr(thread_watch.guards, "exempt", lambda conn, who, by: False)
    monkeypatch.setattr(thread_watch.guard_actions, "note_it",
                        lambda conn, guard, who, ts: calls.append(who) or True)
    monkeypatch.setattr(thread_watch.guard_actions, "delete_notice",
                        lambda client, guard_id, channel_id, ts: True)
    monkeypatch.setattr(thread_watch.guard_actions, "threshold_met", lambda guard, who: None)
    return calls


def test_watched_user_token_reply_is_noted(noted):
    client = Slack(users={USER_ID: {"is_bot": False}})

    assert thread_watch.watched(Ctx(reply(bot_id="B1"), client)) == "noted"
    assert noted == [USER_ID]


def test_watched_bot_user_reply_is_left_alone(noted):
    client = Slack(users={USER_ID: {"is_bot": True}})

    assert thread_watch.watched(Ctx(reply(bot_id="B1"), client)) is None
    assert noted == []


def test_watched_plain_reply_is_noted(noted):
    assert thread_watch.watched(Ctx(reply(), Slack())) == "noted"
    assert noted == [USER_ID]
