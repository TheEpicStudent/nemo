import contextlib

import pytest

from bot.core import privileged, whoami
from bot.nemo import bot_kicks, channelguards, userbots
from bot.nemo.surface import bot_watch

CHANNEL_ID = "C1"
BOT_USER = "UBOT"


@contextlib.contextmanager
def session_of(conn):
    yield conn


class Conn:
    def __init__(self, queued_rows=()):
        self.queued_rows = list(queued_rows)
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return self.queued_rows

    def args_for(self, sql):
        return [args for one, args in self.executed if one == sql]


class Slack:
    def __init__(self, users=None):
        self.users = users or {}

    def users_info(self, user):
        if user not in self.users:
            raise RuntimeError("user_not_found")
        return {"user": self.users[user]}


@pytest.fixture
def kick_state(monkeypatch):
    state = {"kicked": [], "events": [], "outcome": "kicked"}
    monkeypatch.setattr(userbots, "_users", {})
    monkeypatch.setattr(bot_watch, "_apps", {"B1": (BOT_USER, "spammer", "A1")})
    monkeypatch.setattr(bot_watch, "exempt_bot_ids", lambda: {"UEXEMPT"})
    monkeypatch.setattr(whoami, "bot_user_id", lambda client, name: "UNEMO")
    monkeypatch.setattr(privileged, "kick", lambda channel_id, user_id:
                        state["kicked"].append((channel_id, user_id)) or state["outcome"])
    monkeypatch.setattr(channelguards, "record_enforcement",
                        lambda conn, *args, **kwargs: state["events"].append((args, kwargs)) or 1)
    return state


def drain(monkeypatch, queued_rows, client=None):
    conn = Conn(queued_rows)
    monkeypatch.setattr(bot_kicks, "session", lambda: session_of(conn))
    return bot_kicks.drain(client or Slack()), conn


def test_drain_bot_id_subject_kicks_and_records_enforcement(monkeypatch, kick_state):
    drained_count, conn = drain(monkeypatch, [(5, 9, CHANNEL_ID, "B1", 0)])

    assert drained_count == 1
    assert kick_state["kicked"] == [(CHANNEL_ID, BOT_USER)]
    (args, kwargs), = kick_state["events"]
    assert args == (9, CHANNEL_ID, BOT_USER, "kicked")
    assert (kwargs["bot_id"], kwargs["label"], kwargs["notice_wanted"]) == ("B1", "spammer", True)
    assert conn.args_for(bot_kicks.MARK_DONE) == [("kicked", 5)]


def test_drain_bot_user_id_subject_kicks(monkeypatch, kick_state):
    client = Slack(users={BOT_USER: {"is_bot": True, "real_name": "spammer", "profile": {"api_app_id": "A1"}}})

    drain(monkeypatch, [(5, 9, CHANNEL_ID, BOT_USER, 0)], client)

    assert kick_state["kicked"] == [(CHANNEL_ID, BOT_USER)]


@pytest.mark.parametrize(("subject_id", "users", "outcome"), [
    ("UPERSON", {"UPERSON": {"is_bot": False}}, "not a bot"),
    ("UGONE", {}, "not a bot"),
    ("UEXEMPT", {"UEXEMPT": {"is_bot": True}}, "exempt"),
    ("UNEMO", {"UNEMO": {"is_bot": True}}, "exempt"),
])
def test_drain_non_bot_or_exempt_subject_skips_kick(monkeypatch, kick_state, subject_id, users, outcome):
    _drained_count, conn = drain(monkeypatch, [(5, 9, CHANNEL_ID, subject_id, 0)], Slack(users=users))

    assert kick_state["kicked"] == []
    assert conn.args_for(bot_kicks.MARK_DONE) == [(outcome, 5)]


def test_drain_bot_outside_channel_marks_done_without_enforcement_record(monkeypatch, kick_state):
    kick_state["outcome"] = "away"

    _drained_count, conn = drain(monkeypatch, [(5, 9, CHANNEL_ID, "B1", 0)])

    assert kick_state["events"] == []
    assert conn.args_for(bot_kicks.MARK_DONE) == [("away", 5)]


@pytest.mark.parametrize(("attempts", "sql"), [(0, bot_kicks.RECORD_RETRY), (2, bot_kicks.MARK_DONE)])
def test_drain_failed_kick_retries_until_attempts_exhausted(monkeypatch, kick_state, attempts, sql):
    kick_state["outcome"] = "failed: cant_kick_self"

    drained_count, conn = drain(monkeypatch, [(5, 9, CHANNEL_ID, "B1", attempts)])

    assert conn.args_for(sql) == [("failed: cant_kick_self", 5)]
    assert drained_count == (sql == bot_kicks.MARK_DONE)
