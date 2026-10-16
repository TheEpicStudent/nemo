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
    def __init__(self, waiting=()):
        self.waiting = list(waiting)
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return self.waiting

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
def kicking(monkeypatch):
    state = {"kicked": [], "events": [], "outcome": "kicked"}
    monkeypatch.setattr(userbots, "_people", {})
    monkeypatch.setattr(bot_watch, "_apps", {"B1": (BOT_USER, "spammer", "A1")})
    monkeypatch.setattr(bot_watch, "exempt_bot_ids", lambda: {"UEXEMPT"})
    monkeypatch.setattr(whoami, "bot_user_id", lambda client, name: "UNEMO")
    monkeypatch.setattr(privileged, "kick", lambda channel_id, user_id:
                        state["kicked"].append((channel_id, user_id)) or state["outcome"])
    monkeypatch.setattr(channelguards, "record_enforcement",
                        lambda conn, *args, **kwargs: state["events"].append((args, kwargs)) or 1)
    return state


def drain(monkeypatch, waiting, client=None):
    conn = Conn(waiting)
    monkeypatch.setattr(bot_kicks, "session", lambda: session_of(conn))
    return bot_kicks.drain(client or Slack()), conn


def test_drain_kicks_a_bot_by_its_bot_id_and_logs_it(monkeypatch, kicking):
    finished, conn = drain(monkeypatch, [(5, 9, CHANNEL_ID, "B1", 0)])

    assert finished == 1
    assert kicking["kicked"] == [(CHANNEL_ID, BOT_USER)]
    (args, kwargs), = kicking["events"]
    assert args == (9, CHANNEL_ID, BOT_USER, "kicked")
    assert (kwargs["bot_id"], kwargs["label"], kwargs["notice_wanted"]) == ("B1", "spammer", True)
    assert conn.args_for(bot_kicks.FINISHED) == [("kicked", 5)]


def test_drain_kicks_a_bot_user_by_its_user_id(monkeypatch, kicking):
    client = Slack(users={BOT_USER: {"is_bot": True, "real_name": "spammer", "profile": {"api_app_id": "A1"}}})

    drain(monkeypatch, [(5, 9, CHANNEL_ID, BOT_USER, 0)], client)

    assert kicking["kicked"] == [(CHANNEL_ID, BOT_USER)]


@pytest.mark.parametrize(("subject_id", "users", "outcome"), [
    ("UPERSON", {"UPERSON": {"is_bot": False}}, "not a bot"),
    ("UGONE", {}, "not a bot"),
    ("UEXEMPT", {"UEXEMPT": {"is_bot": True}}, "exempt"),
    ("UNEMO", {"UNEMO": {"is_bot": True}}, "exempt"),
])
def test_drain_never_kicks_people_or_exempt_bots(monkeypatch, kicking, subject_id, users, outcome):
    _finished, conn = drain(monkeypatch, [(5, 9, CHANNEL_ID, subject_id, 0)], Slack(users=users))

    assert kicking["kicked"] == []
    assert conn.args_for(bot_kicks.FINISHED) == [(outcome, 5)]


def test_drain_bot_not_in_the_channel_is_done_without_a_log(monkeypatch, kicking):
    kicking["outcome"] = "away"

    _finished, conn = drain(monkeypatch, [(5, 9, CHANNEL_ID, "B1", 0)])

    assert kicking["events"] == []
    assert conn.args_for(bot_kicks.FINISHED) == [("away", 5)]


@pytest.mark.parametrize(("attempts", "sql"), [(0, bot_kicks.RETRY), (2, bot_kicks.FINISHED)])
def test_drain_failed_kick_retries_then_gives_up(monkeypatch, kicking, attempts, sql):
    kicking["outcome"] = "failed: cant_kick_self"

    finished, conn = drain(monkeypatch, [(5, 9, CHANNEL_ID, "B1", attempts)])

    assert conn.args_for(sql) == [("failed: cant_kick_self", 5)]
    assert finished == (sql == bot_kicks.FINISHED)
