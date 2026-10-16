import contextlib
import threading
from types import SimpleNamespace

import pytest

import bot
from bot.core import outbox
from bot.nemo import case_channel, case_queue, channel, guard_actions, guard_notices, loop
from bot.nemo import purge_requests, screening
from bot.nemo.enforcement import purge, sweep
from lib import config
from lib.paths import MIGRATIONS_DIR

ENV_CHANNEL_ID = "CENVONLY"
FIREHOUSE_ID = "C_FIRE"
REPORTS_ID = "C_REPORTS"
LOGS_ID = "C_LOGS"


class Conn:
    def __init__(self, row=None):
        self.row = row
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        return self.row

    def fetchall(self):
        return []

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class SlackUnreachable:
    def __getattr__(self, name):
        def refuse(*args, **kwargs):
            raise AssertionError(f"slack {name} was called without a channel")
        return refuse


class SlackRecorder:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            return {"ts": "9.9", "ok": True}
        return call

    def channels_posted_to(self):
        return [kwargs["channel"] for name, kwargs in self.calls if name == "chat_postMessage"]


@contextlib.contextmanager
def session_of(conn):
    yield conn


def use_settings(monkeypatch, values):
    monkeypatch.setattr(channel, "_settings", {})
    monkeypatch.setattr(channel, "_cards", {})
    monkeypatch.setattr(channel, "_react", {})
    monkeypatch.setattr(channel.channels, "setting", lambda conn, key: values.get(key))
    monkeypatch.setattr(channel.channels, "react_channels", lambda conn: set())
    channel.refresh_channels(Conn())


@pytest.fixture
def no_channel_settings(monkeypatch):
    monkeypatch.setenv("INTERNAL_LOG_CHANNEL_ID", ENV_CHANNEL_ID)
    use_settings(monkeypatch, {})


@pytest.fixture
def split_channels(monkeypatch):
    use_settings(monkeypatch, {channel.channels.FIREHOUSE: FIREHOUSE_ID,
                               channel.channels.REPORTS: REPORTS_ID,
                               channel.channels.LOGS: LOGS_ID})


def test_needs_and_roles_exclude_internal_log_channel_id():
    assert "INTERNAL_LOG_CHANNEL_ID" not in bot.NEEDS[bot.NEMO]
    for role in ("bot", "bot.relay", "bot.nemo", "serve"):
        names = config.ROLES[role]["required"] + config.ROLES[role]["optional"]
        assert "INTERNAL_LOG_CHANNEL_ID" not in names, role


def test_firehouse_channel_without_setting_returns_none(no_channel_settings):
    assert channel.firehouse_channel(Conn()) is None
    assert channel.firehouse_channel() is None


def test_firehouse_channel_changed_setting_returns_new_value(monkeypatch):
    monkeypatch.setattr(channel, "_settings", {})
    values = iter(["CFIRST", "CSECOND"])
    monkeypatch.setattr(channel.channels, "setting", lambda conn, key: next(values))

    assert channel.firehouse_channel(Conn()) == "CFIRST"
    assert channel.firehouse_channel(Conn()) == "CSECOND"
    assert channel.firehouse_channel() == "CSECOND"


def test_refresh_channels_loads_firehouse_reports_and_log_channels(split_channels):
    assert (channel.firehouse_channel(), channel.reports_channel(), channel.log_channel()) == (
        FIREHOUSE_ID, REPORTS_ID, LOGS_ID)


def test_case_channels_returns_firehouse_and_reports_not_log(split_channels):
    assert channel.case_channels() == {FIREHOUSE_ID, REPORTS_ID}


def test_case_channels_without_settings_returns_react_channels(no_channel_settings, monkeypatch):
    monkeypatch.setattr(channel, "_react", {"ids": {"CREACT"}})

    assert channel.case_channels() == {"CREACT"}


def patch_fetch_case(monkeypatch):
    monkeypatch.setattr(channel, "fetch_case", lambda conn, case_id: {
        "case_id": 15, "report_id": 10, "forwarded_ts": None, "card_digest": None,
        "card_channel_id": None, "body": "test", "blocks": None, "shares": [], "assignees": [],
        "resolved_at": None, "resolution": None, "url": None, "is_anonymous": True,
        "reporter_user_id": None, "message_id": None})


def test_post_report_posts_in_reports_channel(split_channels, monkeypatch):
    patch_fetch_case(monkeypatch)
    client, conn = SlackRecorder(), Conn()

    channel.post_report(client, conn, 15)

    assert client.channels_posted_to()[0] == REPORTS_ID
    assert conn.args_for("SET forwarded_ts = %s")[0][2] == REPORTS_ID


def test_post_report_without_reports_channel_skips_claim(no_channel_settings, monkeypatch):
    patch_fetch_case(monkeypatch)
    conn = Conn()

    assert channel.post_report(SlackUnreachable(), conn, 15) is None
    assert conn.args_for(channel.CLAIM_CARD) == []


def test_post_missing_card_posts_in_firehouse(split_channels, monkeypatch):
    posted = []
    monkeypatch.setattr(case_queue, "post", lambda client, conn, case_id, channel_id:
                        posted.append(channel_id))

    case_queue.post_missing_card(SlackUnreachable(), Conn(row=(7,)), 7)

    assert posted == [FIREHOUSE_ID]


def test_post_missing_card_without_firehouse_returns_none(no_channel_settings, monkeypatch):
    monkeypatch.setattr(case_queue, "post", lambda *args: pytest.fail("a card was posted"))

    assert case_queue.post_missing_card(SlackUnreachable(), Conn(row=(7,)), 7) is None


def test_post_outbox_reply_without_firehouse_returns_none(no_channel_settings, monkeypatch):
    monkeypatch.setattr(channel.profile, "profile", lambda *args: pytest.fail("profile was read"))

    assert channel.post_outbox_reply(SlackUnreachable(), "1.1", "USTAFF", "hello", True) is None


def test_guard_notices_drain_without_log_channel_returns_false(no_channel_settings, monkeypatch):
    monkeypatch.setattr(guard_notices, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(guard_notices.channelguards, "notice_groups",
                        lambda *args: pytest.fail("notices were claimed"))

    assert guard_notices.drain(SlackUnreachable()) is False


def test_post_destroy_notice_posts_in_log_channel(split_channels):
    client = SlackRecorder()

    guard_actions.post_destroy_notice(client, Conn(), "C0LOUD", "1.1", "UMOD")

    assert client.channels_posted_to() == [LOGS_ID]


def test_post_destroy_notice_without_log_channel_posts_nothing(no_channel_settings):
    client = SlackRecorder()

    guard_actions.post_destroy_notice(client, Conn(), "C0LOUD", "1.1", "UMOD")

    assert client.calls == []


def test_purge_report_posts_in_log_channel(split_channels, monkeypatch):
    monkeypatch.setattr(purge, "summary", lambda *args: "purged")
    client = SlackRecorder()

    purge.report(client, SimpleNamespace(id=4), 0, 0, None)

    assert client.channels_posted_to() == [LOGS_ID]


def test_purge_report_without_log_channel_posts_nothing(no_channel_settings, monkeypatch):
    monkeypatch.setattr(purge, "summary", lambda *args: "purged")
    client = SlackRecorder()

    purge.report(client, SimpleNamespace(id=4), 0, 0, None)

    assert client.calls == []


def test_log_channel_mention_returns_log_channel_link(split_channels):
    assert purge_requests.log_channel_mention() == f"<#{LOGS_ID}>"


def test_log_channel_mention_without_log_channel_returns_generic_label(no_channel_settings):
    assert purge_requests.log_channel_mention() == "log channel"


def test_post_to_internal_log_posts_in_log_channel(split_channels):
    client = SlackRecorder()

    assert screening.post_to_internal_log(client, Conn(), "UNEW", "example.com",
                                          next(iter(screening.OUTCOME_NOTICES))) == LOGS_ID
    assert client.channels_posted_to() == [LOGS_ID]


def test_sweep_ending_posts_expiry_notice_in_firehouse(split_channels, monkeypatch):
    guard = {"id": 3, "subject_id": "USUB", "kind": "shush", "channel_id": None, "case_id": None,
             "expires_at": None}
    monkeypatch.setattr(sweep, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(sweep, "ending_window", lambda conn: 36)
    monkeypatch.setattr(sweep.memberguards, "ending_not_notified", lambda conn, hours: [guard])
    monkeypatch.setattr(sweep.memberguards, "record_enforcement", lambda *args, **kwargs: None)
    monkeypatch.setattr(sweep, "ending_line", lambda one: "line")
    posted = []
    monkeypatch.setattr(sweep, "post_expiry_notice",
                        lambda client, guards, channel_id: posted.append(channel_id))

    sweep.sweep_ending(SlackUnreachable())

    assert posted == [FIREHOUSE_ID]


def test_pending_reactions_sql_coalesces_report_card_channel():
    assert "coalesce(o.asked_in_channel, r.card_channel_id)" in outbox.PENDING_REACTIONS
    assert "LEFT JOIN fd.case_reports r ON r.id = c.report_id" in outbox.PENDING_REACTIONS


def test_mark_outbox_results_reacts_in_pending_row_channel(split_channels, monkeypatch):
    reaction_targets = []
    monkeypatch.setattr(case_channel, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(case_channel.outbox, "pending_reactions", lambda conn: [(1, REPORTS_ID, "1.1", None, None)])
    monkeypatch.setattr(case_channel.outbox, "mark_reacted", lambda conn, outbox_id: None)
    monkeypatch.setattr(case_channel.CaseChannel, "add_reaction", lambda self, at, emoji: reaction_targets.append(at))

    case_channel.CaseChannel(SlackUnreachable()).mark_outbox_results()

    assert reaction_targets == [(REPORTS_ID, "1.1")]


def test_mark_outbox_results_without_channel_does_not_mark_reacted(no_channel_settings, monkeypatch):
    monkeypatch.setattr(case_channel, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(case_channel.outbox, "pending_reactions", lambda conn: [(1, None, "1.1", None, None)])
    monkeypatch.setattr(case_channel.outbox, "mark_reacted", lambda conn, outbox_id: pytest.fail("ticked"))

    case_channel.CaseChannel(SlackUnreachable()).mark_outbox_results()


def test_loop_start_refreshes_channels(monkeypatch):
    conn = Conn()
    refreshed = []
    monkeypatch.setattr(loop, "session", lambda: session_of(conn))
    for module in (loop.guards, loop.channelguards, loop.memberguards, loop.automod,
                   loop.responses, loop.screening):
        monkeypatch.setattr(module, "refresh", lambda conn: 0)
    monkeypatch.setattr(loop.purge, "requeue_interrupted", lambda conn: [])
    monkeypatch.setattr(loop.loops, "run_on_wake", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop.loops, "start_listener", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop.loops, "run_periodically", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop.loops, "run_on_timer", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop.channel, "refresh_channels", lambda conn: refreshed.append(conn))

    loop.start(SimpleNamespace(client=None), threading.Event())

    assert refreshed == [conn]


def test_reports_and_log_channels_migration_copies_firehouse():
    sql = (MIGRATIONS_DIR / "0235_reports_and_log_channels.sql").read_text()

    assert f"('{channel.channels.REPORTS}'), ('{channel.channels.LOGS}')" in sql
    assert f"WHERE firehouse.key = '{channel.channels.FIREHOUSE}'" in sql
    assert "ON CONFLICT (key) DO NOTHING" in sql
