import contextlib

import pytest

from bot.nemo import case_actions, channel, handlers
from bot.nemo.surface import ENTRIES, reaction_watch

BOT = "UNEMO"
ROOM = "C_FIRE"
CARD = "100.000"


class Conn:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.ran = []

    def execute(self, sql, args=None):
        self.ran.append((sql, args))
        return self

    def fetchone(self):
        for mark, row in self.answers.items():
            if mark in self.ran[-1][0]:
                return row
        return None

    def fetchall(self):
        row = self.fetchone()
        return [row] if row else []


class Slack:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda **kwargs: self.calls.append((name, kwargs)) or {"ok": True}

    def made(self, name):
        return [kwargs for called, kwargs in self.calls if called == name]


class Ctx:
    def __init__(self, payload, client=None):
        self.payload = payload
        self.client = client or Slack()


def test_a_card_shows_where_its_case_stands():
    assert channel.card_mark({}) == "hourglass_flowing_sand"
    assert channel.card_mark({"resolved_at": "x", "resolution": "duplicate"}) == "repeat"
    assert channel.card_mark({"resolved_at": "x", "resolution": "no_action"}) == "white_check_mark"
    assert channel.card_mark({"resolved_at": "x", "resolution": "not_conduct"}) is None


def test_a_fresh_card_only_gains_its_mark():
    slack = Slack()

    channel.mark_card(slack, ROOM, CARD, {}, fresh=True)

    assert slack.calls == [("reactions_add", {"channel": ROOM, "timestamp": CARD,
                                              "name": "hourglass_flowing_sand"})]


def test_a_redrawn_card_drops_the_marks_it_no_longer_wants():
    slack = Slack()

    channel.mark_card(slack, ROOM, CARD, {"resolved_at": "x", "resolution": "duplicate"})

    assert [kwargs["name"] for kwargs in slack.made("reactions_remove")] == [
        "hourglass_flowing_sand", "white_check_mark", "check"]
    assert [kwargs["name"] for kwargs in slack.made("reactions_add")] == ["repeat"]


def test_a_case_closed_as_not_conduct_keeps_only_the_x_it_was_given():
    slack = Slack()

    channel.mark_card(slack, ROOM, CARD, {"resolved_at": "x", "resolution": "not_conduct"})

    assert slack.made("reactions_add") == []
    assert "hourglass_flowing_sand" in [kwargs["name"] for kwargs in slack.made("reactions_remove")]


def test_a_change_of_standing_alone_redraws_the_card():
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Case 2"}}]
    assert channel.digest_of(blocks, "hourglass_flowing_sand") != channel.digest_of(
        blocks, "white_check_mark")


def test_a_check_closes_as_action_taken_only_while_an_action_stands(monkeypatch):
    closed = []
    monkeypatch.setattr(case_actions, "resolve",
                        lambda conn, case_id, values, by: closed.append(values) or 0)

    monkeypatch.setattr(case_actions, "live_actions", lambda conn, case_id: [{"id": 1}])
    assert case_actions.close_quietly(Conn(), 2, None, "UME") == "action_taken"
    monkeypatch.setattr(case_actions, "live_actions", lambda conn, case_id: [])
    assert case_actions.close_quietly(Conn(), 2, None, "UME") == "no_action"
    assert case_actions.close_quietly(Conn(), 2, "not_conduct", "UME") == "not_conduct"

    assert all(not one["notify_reporter"] and one["member_note"] is None for one in closed)


def test_closing_a_case_already_closed_says_so(monkeypatch):
    monkeypatch.setattr(case_actions, "resolve", lambda conn, case_id, values, by: None)
    monkeypatch.setattr(case_actions, "live_actions", lambda conn, case_id: [])
    assert case_actions.close_quietly(Conn(), 2, None, "UME") is None


def test_resolving_from_the_thread_tells_the_reporter(monkeypatch):
    asked = []
    monkeypatch.setattr(case_actions, "live_actions", lambda conn, case_id: [])
    monkeypatch.setattr(case_actions, "resolve",
                        lambda conn, case_id, values, by: asked.append(values) or 1)

    assert case_actions.resolve_and_tell(Conn(), 2, "thanks", "UME") == ("no_action", 1)
    assert asked[0]["notify_reporter"] and asked[0]["message"] == "thanks"


def test_a_case_already_closed_still_lets_the_reporter_hear(monkeypatch):
    monkeypatch.setattr(case_actions, "live_actions", lambda conn, case_id: [])
    monkeypatch.setattr(case_actions, "resolve", lambda conn, case_id, values, by: None)
    monkeypatch.setattr(case_actions, "close_reports", lambda conn, case_id, message, by: 1)

    assert case_actions.resolve_and_tell(Conn(), 2, "thanks", "UME") == (None, 1)


@pytest.fixture
def reacting(monkeypatch):
    heard = {"closed": [], "after": []}

    @contextlib.contextmanager
    def one_session():
        yield Conn({"FROM fd.case_reports WHERE forwarded_ts": (23,)})

    monkeypatch.setattr(reaction_watch, "session", one_session)
    monkeypatch.setattr(reaction_watch.whoami, "bot_user_id", lambda client, name: BOT)
    monkeypatch.setattr(reaction_watch.access, "may",
                        lambda conn, who, needs, case=None: (True, None))
    monkeypatch.setattr(
        reaction_watch.case_actions, "close_quietly",
        lambda conn, case_id, resolution, who: heard["closed"].append((case_id, resolution))
        or (resolution or "no_action"),
    )
    monkeypatch.setattr(reaction_watch, "after_resolve",
                        lambda client, case_id, resolution, who: heard["after"].append(resolution))
    return heard


def on_card(mark, who="UME"):
    return Ctx({"reaction": mark, "user": who,
                "item": {"type": "message", "channel": ROOM, "ts": CARD}})


def test_a_check_on_the_card_closes_by_what_happened(reacting):
    assert reaction_watch.closed_on_card(on_card("white_check_mark")) == 23
    assert reacting["closed"] == [(23, None)]
    assert reacting["after"] == ["no_action"]


def test_an_x_on_the_card_closes_it_as_not_conduct(reacting):
    reaction_watch.closed_on_card(on_card("x"))
    assert reacting["closed"] == [(23, "not_conduct")]


def test_nemos_own_marks_close_nothing(reacting):
    assert reaction_watch.closed_on_card(on_card("white_check_mark", who=BOT)) is None
    assert reacting["closed"] == []


def test_a_reaction_without_case_resolve_closes_nothing(reacting, monkeypatch):
    monkeypatch.setattr(reaction_watch.access, "may",
                        lambda conn, who, needs, case=None: (False, "no"))
    assert reaction_watch.closed_on_card(on_card("x")) is None
    assert reacting["closed"] == []


def test_other_reactions_on_the_card_are_left_alone(reacting):
    assert reaction_watch.closed_on_card(on_card("eyes")) is None
    assert reacting["closed"] == []


class App:
    def action(self, key):
        return lambda fn: fn

    def view(self, key):
        return lambda fn: fn


def watcher():
    return next(one for one in ENTRIES if one.tag == "handlers.on_message")


@pytest.fixture
def thread(monkeypatch):
    heard = {"after": []}
    handlers.register(App())

    @contextlib.contextmanager
    def one_session():
        yield Conn()

    monkeypatch.setattr(handlers, "session", one_session)
    monkeypatch.setattr(handlers, "case_channels", lambda conn=None: {ROOM})
    monkeypatch.setattr(handlers.chat, "case_of_thread", lambda conn, ts: 23)
    monkeypatch.setattr(handlers.access, "may", lambda conn, who, needs, case=None: (True, None))
    monkeypatch.setattr(handlers, "after_resolve",
                        lambda client, case_id, resolution, who: heard["after"].append(resolution))
    return heard


def said(text):
    return Ctx({"channel": ROOM, "ts": "2.0", "thread_ts": CARD, "user": "UME", "text": text})


def test_resolve_in_the_thread_closes_the_case_and_tells_the_reporter(thread, monkeypatch):
    monkeypatch.setattr(handlers, "resolve_and_tell",
                        lambda conn, case_id, message, by: ("no_action", 1))
    ctx = said("!resolve")

    watcher().fn(ctx)

    assert ctx.client.made("reactions_add") == [{"channel": ROOM, "timestamp": "2.0",
                                                 "name": "check-check"}]
    assert thread["after"] == ["no_action"]


def test_resolve_on_a_closed_case_only_tells_the_reporter(thread, monkeypatch):
    monkeypatch.setattr(handlers, "resolve_and_tell",
                        lambda conn, case_id, message, by: (None, 1))
    ctx = said("!Resolve ")

    watcher().fn(ctx)

    assert ctx.client.made("reactions_add")[0]["name"] == "check-check"
    assert thread["after"] == []


def test_resolve_with_nothing_left_to_do_says_so_privately(thread, monkeypatch):
    monkeypatch.setattr(handlers, "resolve_and_tell",
                        lambda conn, case_id, message, by: (None, 0))
    ctx = said("!resolve")

    watcher().fn(ctx)

    assert ctx.client.made("chat_postEphemeral")[0]["text"] == (
        "case 23 is already resolved and has no open report")
    assert ctx.client.made("reactions_add") == []


def test_resolve_needs_both_answering_and_resolving(thread, monkeypatch):
    monkeypatch.setattr(handlers.access, "may",
                        lambda conn, who, needs, case=None: (needs != "case.resolve", "no"))
    told = []
    monkeypatch.setattr(handlers, "resolve_and_tell",
                        lambda conn, case_id, message, by: told.append(case_id) or (None, 1))
    ctx = said("!resolve")

    watcher().fn(ctx)

    assert told == []
    assert ctx.client.made("reactions_add")[0]["name"] == "x"
