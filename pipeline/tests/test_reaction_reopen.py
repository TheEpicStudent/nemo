import contextlib

import pytest

from bot.nemo.surface import reaction_watch

BOT_USER_ID = "UNEMO"
MODERATOR_ID = "UMOD"
FIREHOUSE_ID = "C_FIRE"
REACT_CHANNEL_ID = "C_REACT"
CARD_TS = "100.000"
ROOT_TS = "200.000"
CASE_ID = 23


class FakeConn:
    def __init__(self, state):
        self.state = state
        self.sql = None

    def execute(self, sql, args=None):
        self.sql = sql
        return self

    def fetchone(self):
        if self.sql == reaction_watch.CARD_CASE:
            return (CASE_ID,) if self.state["on_card"] else None
        if self.sql == reaction_watch.CASE_RESOLUTION:
            return self.state["resolution"]
        return None

    def fetchall(self):
        return self.state["messages"] if self.sql == reaction_watch.CASE_MESSAGES else []


class FakeSlack:
    def __init__(self, reactions_by_ts, failing=False):
        self.reactions_by_ts = reactions_by_ts
        self.failing = failing

    def reactions_get(self, **kwargs):
        if self.failing:
            raise RuntimeError("ratelimited")
        reactions = [{"name": name, "users": users} for name, users in self.reactions_by_ts.get(kwargs["timestamp"], [])]
        return {"message": {"reactions": reactions}}


class Ctx:
    def __init__(self, payload, client):
        self.payload = payload
        self.client = client


@pytest.fixture
def reopen_calls(monkeypatch):
    state = {"on_card": True, "resolution": ("action_taken",), "may": True, "reopened": [], "after": [],
             "messages": [("card", FIREHOUSE_ID, CARD_TS), ("root", REACT_CHANNEL_ID, ROOT_TS)]}

    @contextlib.contextmanager
    def fake_session():
        yield FakeConn(state)

    monkeypatch.setattr(reaction_watch, "session", fake_session)
    monkeypatch.setattr(reaction_watch.whoami, "bot_user_id", lambda client, name: BOT_USER_ID)
    monkeypatch.setattr(reaction_watch.channels, "react_channels", lambda conn: {REACT_CHANNEL_ID})
    monkeypatch.setattr(reaction_watch.case_queue, "case_for_root", lambda conn, channel_id, ts: CASE_ID)
    monkeypatch.setattr(reaction_watch.access, "may",
                        lambda conn, user_id, key, case_id=None: (state["may"], None))
    monkeypatch.setattr(reaction_watch.case_actions, "reopen",
                        lambda conn, case_id, by: state["reopened"].append((case_id, by)) or True)
    monkeypatch.setattr(reaction_watch, "after_reopen",
                        lambda client, case_id, user_id: state["after"].append((case_id, user_id)))
    return state


def removed(reaction="white_check_mark", user_id=MODERATOR_ID, channel_id=FIREHOUSE_ID, ts=CARD_TS):
    return {"reaction": reaction, "user": user_id, "item": {"type": "message", "channel": channel_id, "ts": ts}}


def test_reaction_removed_without_remaining_close_reaction_reopens_case(reopen_calls):
    client = FakeSlack({CARD_TS: [("white_check_mark", [BOT_USER_ID])]})

    assert reaction_watch.reopen_case_on_reaction_removed(Ctx(removed(), client)) == CASE_ID
    assert reopen_calls["reopened"] == [(CASE_ID, MODERATOR_ID)]
    assert reopen_calls["after"] == [(CASE_ID, MODERATOR_ID)]


@pytest.mark.parametrize("remaining_ts", [CARD_TS, ROOT_TS])
def test_reaction_removed_with_another_close_reaction_keeps_case_closed(reopen_calls, remaining_ts):
    client = FakeSlack({remaining_ts: [("check-green", ["UOTHER"])]})

    assert reaction_watch.reopen_case_on_reaction_removed(Ctx(removed(), client)) is None
    assert reopen_calls["reopened"] == []


def test_reaction_removed_ignores_roots_outside_react_channels(reopen_calls):
    reopen_calls["messages"] = [("card", FIREHOUSE_ID, CARD_TS), ("root", "C_OTHER", ROOT_TS)]
    client = FakeSlack({ROOT_TS: [("white_check_mark", ["UOTHER"])]})

    assert reaction_watch.reopen_case_on_reaction_removed(Ctx(removed(), client)) == CASE_ID


def test_x_reaction_removed_reopens_case(reopen_calls):
    assert reaction_watch.reopen_case_on_reaction_removed(Ctx(removed(reaction="x"), FakeSlack({}))) == CASE_ID


@pytest.mark.parametrize(("event", "change"), [
    (removed(user_id=BOT_USER_ID), {}),
    (removed(reaction="eyes"), {}),
    (removed(), {"resolution": None}),
    (removed(), {"resolution": ("duplicate",)}),
    (removed(), {"may": False}),
    (removed(), {"on_card": False}),
])
def test_reaction_removed_that_does_not_qualify_leaves_case_alone(reopen_calls, monkeypatch, event, change):
    reopen_calls.update(change)
    if not reopen_calls["on_card"]:
        monkeypatch.setattr(reaction_watch.case_queue, "case_for_root", lambda conn, channel_id, ts: None)

    assert reaction_watch.reopen_case_on_reaction_removed(Ctx(event, FakeSlack({}))) is None
    assert reopen_calls["reopened"] == []


def test_reaction_removed_on_root_in_react_channel_reopens_case(reopen_calls):
    reopen_calls["on_card"] = False
    event = removed(channel_id=REACT_CHANNEL_ID, ts=ROOT_TS)

    assert reaction_watch.reopen_case_on_reaction_removed(Ctx(event, FakeSlack({}))) == CASE_ID


def test_reaction_removed_when_reactions_cannot_be_read_keeps_case_closed(reopen_calls):
    assert reaction_watch.reopen_case_on_reaction_removed(Ctx(removed(), FakeSlack({}, failing=True))) is None
    assert reopen_calls["reopened"] == []


def test_case_messages_query_covers_root_card_and_report_cards():
    sql = reaction_watch.CASE_MESSAGES
    assert "c.card_thread_ts IS NOT NULL" in sql
    assert "c.card_ts IS NOT NULL" in sql
    assert "r.forwarded_ts IS NOT NULL" in sql
