import contextlib

import pytest

from bot.nemo import case_actions, channel, handlers
from bot.nemo.surface import ENTRIES, reaction_watch

BOT = "UNEMO"
CHANNEL_ID = "C_FIRE"
CARD = "100.000"


class Conn:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        for mark, row in self.answers.items():
            if mark in self.executed[-1][0]:
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

    def calls_to(self, name):
        return [kwargs for method, kwargs in self.calls if method == name]


class Ctx:
    def __init__(self, payload, client=None):
        self.payload = payload
        self.client = client or Slack()


def test_card_mark_reflects_case_state():
    assert channel.card_mark({}) == "hourglass_flowing_sand"
    assert channel.card_mark({"resolved_at": "x", "resolution": "duplicate"}) == "repeat"
    assert channel.card_mark({"resolved_at": "x", "resolution": "no_action"}) == "white_check_mark"
    assert channel.card_mark({"resolved_at": "x", "resolution": "action_taken"}) == "white_check_mark"
    assert channel.card_mark({"resolved_at": "x", "resolution": "not_conduct"}) == "x"


def test_mark_card_new_card_adds_reaction_only():
    slack = Slack()

    channel.mark_card(slack, CHANNEL_ID, CARD, {}, is_new=True)

    assert slack.calls == [("reactions_add", {"channel": CHANNEL_ID, "timestamp": CARD,
                                              "name": "hourglass_flowing_sand"})]


def test_mark_card_resolved_case_removes_stale_reactions():
    slack = Slack()

    channel.mark_card(slack, CHANNEL_ID, CARD, {"resolved_at": "x", "resolution": "duplicate"})

    assert [kwargs["name"] for kwargs in slack.calls_to("reactions_remove")] == [
        "hourglass_flowing_sand", "white_check_mark", "x", "check"]
    assert [kwargs["name"] for kwargs in slack.calls_to("reactions_add")] == ["repeat"]


def test_mark_card_reopened_not_conduct_case_removes_x():
    slack = Slack()

    channel.mark_card(slack, CHANNEL_ID, CARD, {})

    assert "x" in [kwargs["name"] for kwargs in slack.calls_to("reactions_remove")]
    assert [kwargs["name"] for kwargs in slack.calls_to("reactions_add")] == ["hourglass_flowing_sand"]


class ReactionsSlack(Slack):
    def __init__(self, reactions):
        super().__init__()
        self.reactions = reactions

    def reactions_get(self, **kwargs):
        self.calls.append(("reactions_get", kwargs))
        return {"message": {"reactions": self.reactions}}


@pytest.fixture
def nemo_bot_user(monkeypatch):
    monkeypatch.setattr(channel.whoami, "bot_user_id", lambda client, name: BOT)


@pytest.mark.parametrize("resolution", ["not_conduct", "no_action"])
@pytest.mark.parametrize("reaction_name", ["x", "white_check_mark", "check-green", "white_tick::skin-tone-2"])
def test_mark_card_with_human_close_reaction_does_not_add_check(nemo_bot_user, resolution, reaction_name):
    slack = ReactionsSlack([{"name": reaction_name, "users": ["UME"], "count": 1}])

    channel.mark_card(slack, CHANNEL_ID, CARD, {"resolved_at": "x", "resolution": resolution})

    assert slack.calls_to("reactions_add") == []
    assert "white_check_mark" in [kwargs["name"] for kwargs in slack.calls_to("reactions_remove")]


@pytest.mark.parametrize("reactions", [
    [],
    [{"name": "white_check_mark", "users": [BOT], "count": 1}],
    [{"name": "eyes", "users": ["UME"], "count": 1}],
])
def test_mark_card_without_human_close_reaction_adds_x_for_not_conduct(nemo_bot_user, reactions):
    slack = ReactionsSlack(reactions)

    channel.mark_card(slack, CHANNEL_ID, CARD, {"resolved_at": "x", "resolution": "not_conduct"})

    assert [kwargs["name"] for kwargs in slack.calls_to("reactions_add")] == ["x"]


def test_mark_root_not_conduct_adds_x(nemo_bot_user):
    slack = ReactionsSlack([])

    channel.mark_root(slack, CHANNEL_ID, "90.000", CARD, {"resolved_at": "x", "resolution": "not_conduct"})

    assert slack.calls_to("reactions_add") == [{"channel": CHANNEL_ID, "timestamp": "90.000", "name": "x"}]


def test_mark_root_with_human_check_does_not_add_check(nemo_bot_user):
    slack = ReactionsSlack([{"name": "white_tick", "users": ["UME"], "count": 1}])

    channel.mark_root(slack, CHANNEL_ID, "90.000", CARD, {"resolved_at": "x", "resolution": "no_action"})

    assert slack.calls_to("reactions_add") == []
    assert slack.calls_to("reactions_get")[0]["timestamp"] == "90.000"


def test_mark_root_resolved_elsewhere_adds_check(nemo_bot_user):
    slack = ReactionsSlack([])

    channel.mark_root(slack, CHANNEL_ID, "90.000", CARD, {"resolved_at": "x", "resolution": "no_action"})

    assert slack.calls_to("reactions_add") == [
        {"channel": CHANNEL_ID, "timestamp": "90.000", "name": "white_check_mark"}]


def test_mark_card_merged_case_skips_reaction_read(nemo_bot_user):
    slack = ReactionsSlack([{"name": "white_tick", "users": ["UME"], "count": 1}])

    channel.mark_card(slack, CHANNEL_ID, CARD, {"resolved_at": "x", "resolution": "duplicate"})

    assert slack.calls_to("reactions_get") == []
    assert [kwargs["name"] for kwargs in slack.calls_to("reactions_add")] == ["repeat"]


def test_mark_card_reaction_read_failure_adds_check(monkeypatch):
    def fail(client, name):
        raise RuntimeError("auth_test failed")

    monkeypatch.setattr(channel.whoami, "bot_user_id", fail)
    slack = ReactionsSlack([])

    channel.mark_card(slack, CHANNEL_ID, CARD, {"resolved_at": "x", "resolution": "no_action"})

    assert [kwargs["name"] for kwargs in slack.calls_to("reactions_add")] == ["white_check_mark"]


def test_digest_of_differs_for_different_marks():
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": "Case 2"}}]
    assert channel.digest_of(blocks, "hourglass_flowing_sand") != channel.digest_of(
        blocks, "white_check_mark")


def test_close_without_notice_resolution_follows_live_actions_without_reporter_notice(monkeypatch):
    resolved_values = []
    monkeypatch.setattr(case_actions, "resolve",
                        lambda conn, case_id, values, by: resolved_values.append(values) or 0)

    monkeypatch.setattr(case_actions, "live_actions", lambda conn, case_id: [{"id": 1}])
    assert case_actions.close_without_notice(Conn(), 2, None, "UME") == "action_taken"
    monkeypatch.setattr(case_actions, "live_actions", lambda conn, case_id: [])
    assert case_actions.close_without_notice(Conn(), 2, None, "UME") == "no_action"
    assert case_actions.close_without_notice(Conn(), 2, "not_conduct", "UME") == "not_conduct"

    assert all(not one["notify_reporter"] and one["member_note"] is None for one in resolved_values)


def test_close_without_notice_already_closed_case_returns_none(monkeypatch):
    monkeypatch.setattr(case_actions, "resolve", lambda conn, case_id, values, by: None)
    monkeypatch.setattr(case_actions, "live_actions", lambda conn, case_id: [])
    assert case_actions.close_without_notice(Conn(), 2, None, "UME") is None


def test_resolve_and_notify_sets_notify_reporter_and_message(monkeypatch):
    resolve_values = []
    monkeypatch.setattr(case_actions, "live_actions", lambda conn, case_id: [])
    monkeypatch.setattr(case_actions, "resolve",
                        lambda conn, case_id, values, by: resolve_values.append(values) or 1)

    assert case_actions.resolve_and_notify(Conn(), 2, "thanks", "UME") == ("no_action", 1)
    assert resolve_values[0]["notify_reporter"] and resolve_values[0]["message"] == "thanks"


def test_resolve_and_notify_already_closed_case_still_closes_reports(monkeypatch):
    monkeypatch.setattr(case_actions, "live_actions", lambda conn, case_id: [])
    monkeypatch.setattr(case_actions, "resolve", lambda conn, case_id, values, by: None)
    monkeypatch.setattr(case_actions, "close_reports", lambda conn, case_id, message, by: 1)

    assert case_actions.resolve_and_notify(Conn(), 2, "thanks", "UME") == (None, 1)


@pytest.fixture
def reaction_calls(monkeypatch):
    recorded = {"closed": [], "after": []}

    @contextlib.contextmanager
    def one_session():
        yield Conn({"FROM fd.case_reports WHERE forwarded_ts": (23,)})

    monkeypatch.setattr(reaction_watch, "session", one_session)
    monkeypatch.setattr(reaction_watch.whoami, "bot_user_id", lambda client, name: BOT)
    monkeypatch.setattr(reaction_watch.access, "may",
                        lambda conn, user_id, capability, case=None: (True, None))
    monkeypatch.setattr(
        reaction_watch.case_actions, "close_without_notice",
        lambda conn, case_id, resolution, user_id: recorded["closed"].append((case_id, resolution))
        or (resolution or "no_action"),
    )
    monkeypatch.setattr(reaction_watch, "after_resolve",
                        lambda client, case_id, resolution, user_id: recorded["after"].append(resolution))
    return recorded


def on_card(mark, user_id="UME"):
    return Ctx({"reaction": mark, "user": user_id,
                "item": {"type": "message", "channel": CHANNEL_ID, "ts": CARD}})


def test_close_case_on_card_reaction_check_mark_closes_case_without_resolution(reaction_calls):
    assert reaction_watch.close_case_on_card_reaction(on_card("white_check_mark")) == 23
    assert reaction_calls["closed"] == [(23, None)]
    assert reaction_calls["after"] == ["no_action"]


@pytest.mark.parametrize("mark", ["white_tick", "check", "check-green"])
def test_close_case_on_card_reaction_alternate_check_marks_close_case(reaction_calls, mark):
    assert reaction_watch.close_case_on_card_reaction(on_card(mark)) == 23
    assert reaction_calls["closed"] == [(23, None)]


def test_close_case_on_card_reaction_x_closes_as_not_conduct(reaction_calls):
    reaction_watch.close_case_on_card_reaction(on_card("x"))
    assert reaction_calls["closed"] == [(23, "not_conduct")]


def test_close_case_on_card_reaction_by_bot_user_returns_none(reaction_calls):
    assert reaction_watch.close_case_on_card_reaction(on_card("white_check_mark", user_id=BOT)) is None
    assert reaction_calls["closed"] == []


def test_close_case_on_card_reaction_without_case_resolve_returns_none(reaction_calls, monkeypatch):
    monkeypatch.setattr(reaction_watch.access, "may",
                        lambda conn, user_id, capability, case=None: (False, "no"))
    assert reaction_watch.close_case_on_card_reaction(on_card("x")) is None
    assert reaction_calls["closed"] == []


def test_close_case_on_card_reaction_unrelated_mark_returns_none(reaction_calls):
    assert reaction_watch.close_case_on_card_reaction(on_card("eyes")) is None
    assert reaction_calls["closed"] == []


class App:
    def action(self, key):
        return lambda fn: fn

    def view(self, key):
        return lambda fn: fn


def message_handler():
    return next(one for one in ENTRIES if one.tag == "handlers.on_message")


@pytest.fixture
def thread_calls(monkeypatch):
    recorded = {"after": []}
    handlers.register(App())

    @contextlib.contextmanager
    def one_session():
        yield Conn()

    monkeypatch.setattr(handlers, "session", one_session)
    monkeypatch.setattr(handlers, "case_channels", lambda conn=None: {CHANNEL_ID})
    monkeypatch.setattr(handlers.chat, "case_of_thread", lambda conn, ts: 23)
    monkeypatch.setattr(handlers.access, "may", lambda conn, user_id, capability, case=None: (True, None))
    monkeypatch.setattr(handlers.thread_commands.privileged, "delete_message",
                        lambda channel_id, ts, max_retries=2: recorded.setdefault("deleted", []).append(ts))
    monkeypatch.setattr(
        handlers, "after_resolve",
        lambda client, case_id, resolution, user_id, post_log=True: recorded["after"].append((resolution, post_log)),
    )
    monkeypatch.setattr(handlers, "mark_resolution_log_pending",
                        lambda conn, case_id, by: recorded.setdefault("pending_logs", []).append((case_id, by)))
    return recorded


def thread_message(text):
    return Ctx({"channel": CHANNEL_ID, "ts": "2.0", "thread_ts": CARD, "user": "UME", "text": text})


def test_on_message_resolve_command_adds_check_and_marks_resolution_log_pending(thread_calls, monkeypatch):
    monkeypatch.setattr(handlers, "resolve_and_notify",
                        lambda conn, case_id, message, by: ("no_action", 1))
    ctx = thread_message("!resolve")

    message_handler().fn(ctx)

    assert ctx.client.calls_to("reactions_add") == [{"channel": CHANNEL_ID, "timestamp": "2.0",
                                                     "name": "check-check"}]
    assert thread_calls["after"] == [("no_action", False)], "the resolved line waits for the reporter's"
    assert thread_calls["pending_logs"] == [(23, "UME")]


def test_on_message_resolve_command_on_closed_case_adds_check_without_after_resolve(thread_calls, monkeypatch):
    monkeypatch.setattr(handlers, "resolve_and_notify",
                        lambda conn, case_id, message, by: (None, 1))
    ctx = thread_message("!Resolve ")

    message_handler().fn(ctx)

    assert ctx.client.calls_to("reactions_add")[0]["name"] == "check-check"
    assert thread_calls["after"] == []


def test_on_message_resolve_command_with_nothing_to_close_posts_ephemeral_and_deletes_command(thread_calls, monkeypatch):
    monkeypatch.setattr(handlers, "resolve_and_notify",
                        lambda conn, case_id, message, by: (None, 0))
    ctx = thread_message("!resolve")

    message_handler().fn(ctx)

    assert ctx.client.calls_to("chat_postEphemeral")[0]["text"] == (
        "Case 23 is already resolved")
    assert thread_calls["deleted"] == ["2.0"], "a command that did nothing is taken down"
    assert ctx.client.calls_to("reactions_add") == []


def test_on_message_resolve_command_without_case_resolve_posts_denial_and_deletes_command(thread_calls, monkeypatch):
    monkeypatch.setattr(handlers.access, "may",
                        lambda conn, user_id, capability, case=None: (capability != "case.resolve", "no"))
    command_calls = []
    monkeypatch.setattr(handlers, "resolve_and_notify",
                        lambda conn, case_id, message, by: command_calls.append(case_id) or (None, 1))
    ctx = thread_message("!resolve")

    message_handler().fn(ctx)

    assert command_calls == []
    assert ctx.client.calls_to("chat_postEphemeral")[0]["text"] == "no"
    assert thread_calls["deleted"] == ["2.0"]
