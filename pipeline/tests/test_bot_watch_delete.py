import pytest

from bot.core import whoami
from bot.nemo import channelguards
from bot.nemo.surface import bot_watch
from bot.nemo.views import activity

CHANNEL_ID = "C1"
BOT_ID = "B1"
BOT_USER_ID = "U9"
TS = "1700000000.000200"
THREAD_TS = "1700000000.000100"


class Conn:
    def __init__(self):
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        return (1,)


class _conn_context:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *failure):
        return False


class Slack:
    def __init__(self, calls):
        self.calls = calls

    def __getattr__(self, method):
        def call(**kwargs):
            self.calls.append(method)
            return {"ok": True}
        return call


class Ctx:
    def __init__(self, event, client):
        self.payload = event
        self.client = client


class Harness:
    def __init__(self, calls, conn, retry_limits, failures):
        self.calls, self.conn, self.retry_limits, self.failures = calls, conn, retry_limits, failures

    def __iter__(self):
        return iter((self.calls, self.conn))


@pytest.fixture
def harness(monkeypatch):
    calls = []
    conn = Conn()
    channelguards._guards.clear()
    channelguards._guards[(channelguards.BOT_ALLOWLIST, CHANNEL_ID, channelguards.CHANNEL_WIDE)] = channelguards.LiveGuard(
        7, {}, frozenset())
    channelguards._loaded = True
    bot_watch._apps[BOT_ID] = (BOT_USER_ID, "spammer", "A1")
    monkeypatch.setattr(whoami, "bot_user_id", lambda client, name: "UNEMO")
    def delete(channel_id, ts, max_retries=2):
        calls.append("chat.delete")
        retry_limits.append(max_retries)
        if failures:
            raise failures.pop(0)

    retry_limits, failures = [], []
    monkeypatch.setattr(bot_watch.privileged, "delete_message", delete)
    monkeypatch.setattr(bot_watch.privileged, "kick",
                        lambda channel_id, user_id: calls.append("conversations.kick") or "kicked")
    monkeypatch.setattr(bot_watch, "session", lambda: _conn_context(conn))
    yield Harness(calls, conn, retry_limits, failures)
    channelguards._guards.clear()
    channelguards._loaded = False
    bot_watch._apps.clear()


def message(**over):
    return {"channel": CHANNEL_ID, "ts": TS, "bot_id": BOT_ID, "subtype": "bot_message",
            "text": "buy now", **over}


def guard_event_args(conn):
    (args,) = [args for sql, args in conn.executed if "INSERT INTO fd.channel_guard_events" in sql]
    return args


def test_delete_unlisted_bot_message_calls_only_chat_delete(harness):
    calls, _conn = harness

    assert bot_watch.delete_unlisted_bot_message(Ctx(message(), Slack(calls))) == 7
    assert calls == ["chat.delete"]


def test_delete_unlisted_bot_message_records_archive_link(harness):
    calls, conn = harness
    bot_watch.delete_unlisted_bot_message(Ctx(message(), Slack(calls)))

    assert f"{activity.ARCHIVES}/{CHANNEL_ID}/p1700000000000200" in guard_event_args(conn)


def test_delete_unlisted_bot_message_queues_deleted_guard_event(harness):
    calls, conn = harness
    bot_watch.delete_unlisted_bot_message(Ctx(message(), Slack(calls)))

    args = guard_event_args(conn)
    assert args[2] == BOT_USER_ID
    assert args[5] == "deleted"
    assert args[-2:] == (True, False)


def test_kick_unlisted_bot_on_join_kicks_and_queues_guard_event(harness):
    calls, conn = harness
    client = Slack(calls)
    client.users_info = lambda **kwargs: {"user": {
        "is_bot": True, "real_name": "spammer", "profile": {"bot_id": BOT_ID, "api_app_id": "A1"}}}

    assert bot_watch.kick_unlisted_bot_on_join(Ctx({"channel": CHANNEL_ID, "user": BOT_USER_ID}, client)) == 7
    assert calls == ["conversations.kick"]
    args = guard_event_args(conn)
    assert args[5] == "kicked"
    assert args[-3:] == (None, True, False)


def test_message_url_thread_reply_includes_thread_ts():
    assert activity.message_url(CHANNEL_ID, TS, THREAD_TS) == (
        f"{activity.ARCHIVES}/{CHANNEL_ID}/p1700000000000200?thread_ts={THREAD_TS}&cid={CHANNEL_ID}"
    )


def test_message_url_top_level_message_omits_thread_ts():
    assert activity.message_url(CHANNEL_ID, TS) == f"{activity.ARCHIVES}/{CHANNEL_ID}/p1700000000000200"
    assert activity.message_url(CHANNEL_ID, TS, TS) == f"{activity.ARCHIVES}/{CHANNEL_ID}/p1700000000000200"


def throttled():
    failure = RuntimeError("proxy returned 429: budget: nemo:admin:chat.delete is spent")
    failure.http_status = 429
    return failure


def test_delete_unlisted_bot_message_uses_zero_max_retries(harness):
    calls, _conn = harness
    bot_watch.delete_unlisted_bot_message(Ctx(message(), Slack(calls)))

    assert harness.retry_limits == [0]


def test_delete_unlisted_bot_message_throttled_delete_marks_remove_pending(harness, caplog):
    calls, conn = harness
    harness.failures.append(throttled())
    caplog.set_level("INFO", logger="bot.nemo")

    assert bot_watch.delete_unlisted_bot_message(Ctx(message(), Slack(calls))) == 7
    args = guard_event_args(conn)
    assert args[5] == "deleted"
    assert "429" in args[-3]
    assert args[-2:] == (True, True)
    assert any("queued for a retry" in one.getMessage() for one in caplog.records)


def test_delete_unlisted_bot_message_message_not_found_not_queued_for_removal(harness):
    calls, conn = harness
    harness.failures.append(RuntimeError("message_not_found"))

    bot_watch.delete_unlisted_bot_message(Ctx(message(), Slack(calls)))

    args = guard_event_args(conn)
    assert args[-3] is None
    assert args[-1] is False


def test_delete_unlisted_bot_message_logs_delete_latency(harness, caplog):
    calls, _conn = harness
    caplog.set_level("INFO", logger="bot.nemo")
    bot_watch.delete_unlisted_bot_message(Ctx(message(), Slack(calls)))

    assert any("ms after it was posted" in one.getMessage() for one in caplog.records)
