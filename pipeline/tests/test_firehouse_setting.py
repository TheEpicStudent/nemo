import contextlib
import threading
from types import SimpleNamespace

import pytest

import bot
from bot.nemo import case_channel, case_queue, channel, guard_actions, guard_notices, loop
from bot.nemo import purge_requests
from bot.nemo.enforcement import purge
from lib import config

ENV_CHANNEL_ID = "CENVONLY"


class Conn:
    def __init__(self, row=None):
        self.row = row
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append(sql)
        return self

    def fetchone(self):
        return self.row


class SlackUnreachable:
    def __getattr__(self, name):
        def refuse(*args, **kwargs):
            raise AssertionError(f"slack {name} was called without a firehouse channel")
        return refuse


class SlackRecorder:
    def __init__(self):
        self.calls = []

    def chat_postMessage(self, **kwargs):
        self.calls.append(kwargs)
        return {"ts": "1.2"}


@contextlib.contextmanager
def session_of(conn):
    yield conn


@pytest.fixture
def no_firehouse(monkeypatch):
    monkeypatch.setenv("INTERNAL_LOG_CHANNEL_ID", ENV_CHANNEL_ID)
    monkeypatch.setattr(channel, "_internal_log", {})
    monkeypatch.setattr(channel.channels, "setting", lambda conn, key: None)


def test_nemo_needs_no_internal_log_channel_env_var():
    assert "INTERNAL_LOG_CHANNEL_ID" not in bot.NEEDS[bot.NEMO]
    for role in ("bot", "bot.relay", "bot.nemo", "serve"):
        names = config.ROLES[role]["required"] + config.ROLES[role]["optional"]
        assert "INTERNAL_LOG_CHANNEL_ID" not in names, role


def test_internal_log_channel_without_setting_ignores_env_var(no_firehouse):
    assert channel.internal_log_channel(Conn()) is None
    assert channel.internal_log_channel() is None


def test_internal_log_channel_follows_changed_setting(monkeypatch):
    monkeypatch.setattr(channel, "_internal_log", {})
    values = iter(["CFIRST", "CSECOND"])
    monkeypatch.setattr(channel.channels, "setting", lambda conn, key: next(values))

    assert channel.internal_log_channel(Conn()) == "CFIRST"
    assert channel.internal_log_channel(Conn()) == "CSECOND"
    assert channel.internal_log_channel() == "CSECOND"


def test_case_channels_without_firehouse_excludes_none(no_firehouse, monkeypatch):
    monkeypatch.setattr(channel, "_react", {"ids": {"CREACT"}})

    assert channel.case_channels() == {"CREACT"}


def test_post_report_without_firehouse_claims_nothing(no_firehouse, monkeypatch):
    monkeypatch.setattr(channel, "gather", lambda conn, case_id: {"forwarded_ts": None, "report_id": 3})
    conn = Conn()

    assert channel.post_report(SlackUnreachable(), conn, 7) is None
    assert not any("FOR UPDATE" in sql or sql == channel.CLAIM_CARD for sql in conn.executed)


def test_case_queue_card_without_firehouse_posts_nothing(monkeypatch):
    monkeypatch.setattr(case_queue, "internal_log_channel", lambda conn=None: None)
    monkeypatch.setattr(case_queue, "post", lambda *args: pytest.fail("a card was posted"))

    assert case_queue.card(SlackUnreachable(), Conn(row=(7,)), 7) is None


def test_echo_without_firehouse_returns_none(no_firehouse, monkeypatch):
    monkeypatch.setattr(channel.profile, "profile", lambda *args: pytest.fail("profile was read"))

    assert channel.echo(SlackUnreachable(), "1.1", "USTAFF", "hello", True) is None


def test_guard_notices_drain_without_firehouse_claims_nothing(no_firehouse, monkeypatch):
    monkeypatch.setattr(guard_notices, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(guard_notices.channelguards, "notice_groups",
                        lambda *args: pytest.fail("notices were claimed"))

    assert guard_notices.drain(SlackUnreachable()) is False


def test_tick_queued_without_firehouse_leaves_row_unticked(no_firehouse, monkeypatch):
    monkeypatch.setattr(case_channel, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(case_channel.outbox, "to_tick", lambda conn: [(1, None, "1.1", None, None)])
    monkeypatch.setattr(case_channel.outbox, "ticked", lambda conn, outbox_id: pytest.fail("ticked"))

    case_channel.CaseChannel(SlackUnreachable()).tick_queued()


def test_post_destroy_notice_without_firehouse_posts_nothing(no_firehouse):
    client = SlackRecorder()

    guard_actions.post_destroy_notice(client, Conn(), "C0LOUD", "1.1", "UMOD")

    assert client.calls == []


def test_purge_report_without_firehouse_posts_nothing(no_firehouse, monkeypatch):
    monkeypatch.setattr(purge, "summary", lambda *args: "purged")
    client = SlackRecorder()

    purge.report(client, SimpleNamespace(id=4), 0, 0, None)

    assert client.calls == []


def test_log_channel_mention_without_firehouse_names_firehouse_log(no_firehouse):
    assert purge_requests.log_channel_mention() == "the firehouse log"


def test_loop_start_reads_firehouse_and_react_channels(monkeypatch):
    conn = Conn()
    read = []
    monkeypatch.setattr(loop, "session", lambda: session_of(conn))
    for module in (loop.guards, loop.channelguards, loop.memberguards, loop.automod,
                   loop.responses, loop.screening):
        monkeypatch.setattr(module, "refresh", lambda conn: 0)
    monkeypatch.setattr(loop.purge, "requeue_stranded", lambda conn: [])
    monkeypatch.setattr(loop.loops, "draining", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop.loops, "watching", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop.loops, "sweeping", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop.channel, "internal_log_channel",
                        lambda conn=None: read.append(("firehouse", conn)))
    monkeypatch.setattr(loop.channel, "react_channels",
                        lambda conn=None: read.append(("react", conn)))

    loop.start(SimpleNamespace(client=None), threading.Event())

    assert read == [("firehouse", conn), ("react", conn)]
