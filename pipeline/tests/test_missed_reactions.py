import contextlib

import pytest

from bot.nemo import missed_reactions

BOT_USER_ID = "UNEMO"
MODERATOR_ID = "UMOD"
MEMBER_ID = "UMEMBER"
REACT_CHANNEL_ID = "C_REACT"
FIREHOUSE_ID = "C_FIRE"


class FakeConn:
    def __init__(self, messages):
        self.messages = messages

    def execute(self, sql, args=None):
        return self

    def fetchall(self):
        return self.messages


class FakeSlack:
    def __init__(self, reactions_by_ts, failing_ts=()):
        self.reactions_by_ts = reactions_by_ts
        self.failing_ts = failing_ts
        self.requests = []

    def reactions_get(self, **kwargs):
        self.requests.append(kwargs)
        if kwargs["timestamp"] in self.failing_ts:
            raise RuntimeError("message_not_found")
        reactions = [{"name": name, "users": users} for name, users in self.reactions_by_ts.get(kwargs["timestamp"], [])]
        return {"message": {"reactions": reactions}}


@pytest.fixture
def pass_calls(monkeypatch):
    calls = {"messages": [], "may": [], "closed": [], "after": []}

    @contextlib.contextmanager
    def fake_session():
        yield FakeConn(calls["messages"])

    def fake_may(conn, user_id, key, case_id=None):
        calls["may"].append((user_id, key, case_id))
        return (user_id == MODERATOR_ID, None)

    monkeypatch.setattr(missed_reactions, "session", fake_session)
    monkeypatch.setattr(missed_reactions.whoami, "bot_user_id", lambda client, name: BOT_USER_ID)
    monkeypatch.setattr(missed_reactions.channels, "react_channels", lambda conn: {REACT_CHANNEL_ID})
    monkeypatch.setattr(missed_reactions.access, "may", fake_may)
    monkeypatch.setattr(missed_reactions.case_actions, "close_without_notice",
                        lambda conn, case_id, resolution, by: calls["closed"].append((case_id, resolution, by))
                        or (resolution or "no_action"))
    monkeypatch.setattr(missed_reactions.reaction_watch, "after_resolve",
                        lambda client, case_id, resolution, by: calls["after"].append((case_id, resolution, by)))
    return calls


def test_close_reactions_mixed_reactions_returns_close_names_without_skin_tone():
    slack = FakeSlack({"1.0": [("white_check_mark::skin-tone-2", [MODERATOR_ID]), ("eyes", [MEMBER_ID]),
                               ("check-green", [MODERATOR_ID])]})

    assert missed_reactions.close_reactions(slack, FIREHOUSE_ID, "1.0") == \
        [("white_check_mark", [MODERATOR_ID]), ("check-green", [MODERATOR_ID])]
    assert slack.requests == [{"channel": FIREHOUSE_ID, "timestamp": "1.0", "full": True}]


def test_apply_missed_close_reactions_root_and_card_of_one_case_closes_case_once(pass_calls):
    pass_calls["messages"] += [(1, "root", REACT_CHANNEL_ID, "1.0"), (1, "card", REACT_CHANNEL_ID, "1.1")]
    slack = FakeSlack({"1.0": [("white_check_mark", [BOT_USER_ID, MODERATOR_ID])]})

    assert missed_reactions.apply_missed_close_reactions(slack) == [1]
    assert pass_calls["closed"] == [(1, None, MODERATOR_ID)]
    assert pass_calls["after"] == [(1, "no_action", MODERATOR_ID)]
    assert [request["timestamp"] for request in slack.requests] == ["1.0"]
    assert pass_calls["may"] == [(MODERATOR_ID, "case.resolve", None)]


def test_apply_missed_close_reactions_ignores_root_outside_react_channels(pass_calls):
    pass_calls["messages"].append((2, "root", "C_OTHER", "2.0"))
    slack = FakeSlack({"2.0": [("white_check_mark", [MODERATOR_ID])]})

    assert missed_reactions.apply_missed_close_reactions(slack) == []
    assert slack.requests == []


def test_apply_missed_close_reactions_x_on_card_closes_as_not_conduct(pass_calls):
    pass_calls["messages"].append((3, "card", FIREHOUSE_ID, "3.0"))
    slack = FakeSlack({"3.0": [("x", [MODERATOR_ID])]})

    assert missed_reactions.apply_missed_close_reactions(slack) == [3]
    assert pass_calls["closed"] == [(3, "not_conduct", MODERATOR_ID)]
    assert pass_calls["may"] == [(MODERATOR_ID, "case.resolve", 3)]


def test_apply_missed_close_reactions_without_case_resolve_leaves_case_open(pass_calls):
    pass_calls["messages"].append((4, "card", FIREHOUSE_ID, "4.0"))
    slack = FakeSlack({"4.0": [("white_check_mark", [MEMBER_ID])]})

    assert missed_reactions.apply_missed_close_reactions(slack) == []
    assert pass_calls["closed"] == []


def test_apply_missed_close_reactions_continues_after_read_failure(pass_calls):
    pass_calls["messages"] += [(5, "card", FIREHOUSE_ID, "5.0"), (6, "card", FIREHOUSE_ID, "6.0")]
    slack = FakeSlack({"6.0": [("check", [MODERATOR_ID])]}, failing_ts=("5.0",))

    assert missed_reactions.apply_missed_close_reactions(slack) == [6]


def test_apply_missed_close_reactions_already_resolved_case_is_not_announced(pass_calls, monkeypatch):
    monkeypatch.setattr(missed_reactions.case_actions, "close_without_notice", lambda conn, case_id, resolution, by: None)
    pass_calls["messages"].append((7, "card", FIREHOUSE_ID, "7.0"))
    slack = FakeSlack({"7.0": [("white_check_mark", [MODERATOR_ID])]})

    assert missed_reactions.apply_missed_close_reactions(slack) == [7]
    assert pass_calls["after"] == []


def test_open_case_messages_selects_unresolved_root_card_and_report_card():
    sql = missed_reactions.OPEN_CASE_MESSAGES
    assert sql.count("resolved_at IS NULL") == 3
    assert "c.card_thread_ts IS NOT NULL" in sql
    assert "c.card_ts IS NOT NULL" in sql
    assert "r.forwarded_ts IS NOT NULL" in sql
