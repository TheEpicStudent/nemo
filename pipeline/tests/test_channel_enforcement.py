import pytest

from bot.nemo import channelguards, exemptions, userbots
from bot.nemo.enforcement import account_age, readonly, slowmode

USER_ID = "U1"
CHANNEL_ID = "C1"
TS = "1700000000.000100"
THREAD = "1700000000.000000"


class Conn:
    def __init__(self, tick=None, remaining=None, exempt=False):
        self.tick = tick
        self.remaining = remaining
        self.exempt = exempt
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        sql, _ = self.executed[-1]
        if sql == exemptions.EXEMPT:
            return (self.exempt,)
        if "INSERT INTO fd.slowmode_clock" in sql:
            return self.tick
        if "FROM fd.slowmode_clock" in sql:
            return (self.remaining,) if self.remaining is not None else None
        if "fd.member_joins" in sql:
            return (self.remaining,) if self.remaining is not None else None
        return (1,)

    def fetchall(self):
        return []

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class Slack:
    def __init__(self, users=None):
        self.ephemeral = []
        self.users = users or {}

    def users_info(self, user):
        if user not in self.users:
            raise RuntimeError("user_not_found")
        return {"user": self.users[user]}

    def chat_postEphemeral(self, **kwargs):
        self.ephemeral.append(kwargs)
        return {"ok": True}


class Ctx:
    def __init__(self, event, client=None):
        self.payload = event
        self.client = client or Slack()


class _conn_context:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *failure):
        return False


def message(text="a message", **over):
    return {"user": USER_ID, "channel": CHANNEL_ID, "ts": TS, "text": text, **over}


@pytest.fixture(autouse=True)
def reset_guard_cache(monkeypatch):
    monkeypatch.setattr(userbots, "_users", {})
    channelguards._guards.clear()
    channelguards._loaded = False
    yield
    channelguards._guards.clear()
    channelguards._loaded = False


def guard(kind, settings=None, allowed=()):
    channelguards._guards[(kind, CHANNEL_ID, channelguards.CHANNEL_WIDE)] = channelguards.LiveGuard(7, settings or {}, frozenset(allowed))
    channelguards._loaded = True


def install_fakes(monkeypatch, module, conn, removes=True):
    monkeypatch.setattr(module, "session", lambda: _conn_context(conn))
    removed = []

    def remove(_client, channel_id, ts):
        if not removes:
            raise RuntimeError("could not remove")
        removed.append((channel_id, ts))
        return True

    monkeypatch.setattr(module.guard_actions, "remove", remove)
    return removed


def test_active_guard_before_cache_load_returns_none_and_allows():
    assert channelguards.active_guard(CHANNEL_ID, channelguards.READONLY) is None
    assert channelguards.allows(CHANNEL_ID, USER_ID, kind=channelguards.READONLY)


def test_readonly_on_message_top_level_removes_and_records_event(monkeypatch):
    guard(channelguards.READONLY)
    conn = Conn()
    removed = install_fakes(monkeypatch, readonly, conn)
    client = Slack()

    assert readonly.on_message(Ctx(message(), client)) is True
    assert removed == [(CHANNEL_ID, TS)]
    assert conn.args_for("INSERT INTO fd.channel_guard_events")


def test_readonly_on_message_user_token_post_with_bot_id_is_removed(monkeypatch):
    guard(channelguards.READONLY)
    removed = install_fakes(monkeypatch, readonly, Conn())
    client = Slack(users={USER_ID: {"is_bot": False}})

    assert readonly.on_message(Ctx(message(bot_id="B1"), client)) is True
    assert removed == [(CHANNEL_ID, TS)]


def test_readonly_on_message_bot_user_post_is_ignored(monkeypatch):
    guard(channelguards.READONLY)
    removed = install_fakes(monkeypatch, readonly, Conn())
    client = Slack(users={USER_ID: {"is_bot": True}})

    assert readonly.on_message(Ctx(message(bot_id="B1"), client)) is None
    assert removed == []


def test_readonly_on_message_exempt_member_is_ignored(monkeypatch):
    guard(channelguards.READONLY)
    conn = Conn(exempt=True)
    removed = install_fakes(monkeypatch, readonly, conn)

    assert readonly.on_message(Ctx(message())) is None
    assert removed == []
    assert conn.args_for(exemptions.EXEMPT) == [(USER_ID, exemptions.STAFF_CAPABILITY, USER_ID)]


def test_readonly_on_message_ephemeral_quotes_message_text(monkeypatch):
    guard(channelguards.READONLY)
    client = Slack()
    install_fakes(monkeypatch, readonly, Conn())
    readonly.on_message(Ctx(message("the thing I typed"), client))

    sent = client.ephemeral[0]
    assert "Your message" not in sent["text"]
    assert sent["blocks"][1]["elements"][0] == {
        "type": "rich_text_preformatted", "elements": [{"type": "text", "text": "the thing I typed"}],
    }


def test_readonly_on_message_thread_reply_is_ignored(monkeypatch):
    guard(channelguards.READONLY)
    conn = Conn()
    removed = install_fakes(monkeypatch, readonly, conn)

    assert readonly.on_message(Ctx(message(thread_ts=THREAD))) is None
    assert removed == []


def test_readonly_on_message_thread_broadcast_is_removed(monkeypatch):
    guard(channelguards.READONLY)
    removed = install_fakes(monkeypatch, readonly, Conn())
    readonly.on_message(Ctx(message(thread_ts=THREAD, subtype="thread_broadcast")))

    assert removed == [(CHANNEL_ID, TS)]


def test_readonly_on_message_thread_reply_with_threads_setting_is_removed(monkeypatch):
    guard(channelguards.READONLY, {"threads": True})
    removed = install_fakes(monkeypatch, readonly, Conn())

    assert readonly.on_message(Ctx(message(thread_ts=THREAD))) is True
    assert removed == [(CHANNEL_ID, TS)]


def test_readonly_on_message_allowed_member_is_ignored(monkeypatch):
    guard(channelguards.READONLY, allowed=[USER_ID])
    removed = install_fakes(monkeypatch, readonly, Conn())

    assert readonly.on_message(Ctx(message())) is None
    assert removed == []


def test_readonly_on_message_removal_failure_records_no_event(monkeypatch):
    guard(channelguards.READONLY)
    conn = Conn()
    install_fakes(monkeypatch, readonly, conn, removes=False)

    assert readonly.on_message(Ctx(message())) is None
    assert not conn.args_for("INSERT INTO fd.channel_guard_events")


def test_slowmode_on_message_first_message_is_ignored(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    conn = Conn(tick=("now",))
    removed = install_fakes(monkeypatch, slowmode, conn)

    assert slowmode.on_message(Ctx(message())) is None
    assert removed == []


def test_slowmode_on_message_inside_interval_removes_and_notifies(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    conn = Conn(tick=None, remaining=12)
    removed = install_fakes(monkeypatch, slowmode, conn)
    client = Slack()

    assert slowmode.on_message(Ctx(message(), client)) is True
    assert removed == [(CHANNEL_ID, TS)]
    assert client.ephemeral[0]["text"] == "*Slow mode*: next message in 12s"


def test_slowmode_on_message_exempt_member_skips_clock(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    conn = Conn(tick=None, remaining=12, exempt=True)
    removed = install_fakes(monkeypatch, slowmode, conn)

    assert slowmode.on_message(Ctx(message())) is None
    assert removed == []
    assert not conn.args_for("INSERT INTO fd.slowmode_clock")


def test_slowmode_on_message_thread_without_threads_setting_is_ignored(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    removed = install_fakes(monkeypatch, slowmode, Conn(tick=None, remaining=5))

    assert slowmode.on_message(Ctx(message(thread_ts=THREAD))) is None
    assert removed == []


def test_slowmode_on_message_thread_uses_thread_ts_clock_key(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30, "threads": True})
    conn = Conn(tick=None, remaining=5)
    install_fakes(monkeypatch, slowmode, conn)
    slowmode.on_message(Ctx(message(thread_ts=THREAD)))

    assert conn.args_for("INSERT INTO fd.slowmode_clock")[0][1] == THREAD


def test_slowmode_on_message_thread_notice_posts_in_thread(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30, "threads": True})
    conn = Conn(tick=None, remaining=5)
    install_fakes(monkeypatch, slowmode, conn)
    client = Slack()

    slowmode.on_message(Ctx(message(thread_ts=THREAD), client))

    assert client.ephemeral[0]["thread_ts"] == THREAD


def test_slowmode_on_message_channel_notice_has_no_thread_ts(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    conn = Conn(tick=None, remaining=5)
    install_fakes(monkeypatch, slowmode, conn)
    client = Slack()

    slowmode.on_message(Ctx(message(), client))

    assert client.ephemeral[0]["thread_ts"] is None


def test_slowmode_on_message_channel_message_uses_empty_clock_key(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    conn = Conn(tick=("now",))
    install_fakes(monkeypatch, slowmode, conn)
    slowmode.on_message(Ctx(message()))

    assert conn.args_for("INSERT INTO fd.slowmode_clock")[0][1] == ""


def test_slowmode_on_message_allowed_member_is_ignored(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30}, allowed=[USER_ID])
    removed = install_fakes(monkeypatch, slowmode, Conn(tick=None, remaining=5))

    assert slowmode.on_message(Ctx(message())) is None
    assert removed == []


def test_slowmode_on_message_zero_seconds_is_ignored(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 0})
    removed = install_fakes(monkeypatch, slowmode, Conn(tick=None, remaining=5))

    assert slowmode.on_message(Ctx(message())) is None
    assert removed == []


def test_format_wait_switches_to_minutes_at_ninety_seconds():
    assert slowmode.card.format_wait(45) == "45s"
    assert slowmode.card.format_wait(1) == "1s"
    assert slowmode.card.format_wait(90) == "2m"


def test_account_age_on_message_new_member_removes_and_notifies(monkeypatch):
    guard(channelguards.ACCOUNT_AGE, {"min_age_days": 7})
    conn = Conn(remaining=3)
    removed = install_fakes(monkeypatch, account_age, conn)
    client = Slack()

    assert account_age.on_message(Ctx(message(), client)) is True
    assert removed == [(CHANNEL_ID, TS)]
    assert "3 days" in client.ephemeral[0]["text"]


def test_account_age_on_message_exempt_member_is_ignored(monkeypatch):
    guard(channelguards.ACCOUNT_AGE, {"min_age_days": 7})
    conn = Conn(remaining=3, exempt=True)
    removed = install_fakes(monkeypatch, account_age, conn)

    assert account_age.on_message(Ctx(message())) is None
    assert removed == []


def test_account_age_on_message_old_member_is_ignored(monkeypatch):
    guard(channelguards.ACCOUNT_AGE, {"min_age_days": 7})
    removed = install_fakes(monkeypatch, account_age, Conn(remaining=None))

    assert account_age.on_message(Ctx(message())) is None
    assert removed == []


def test_account_age_on_message_unknown_join_is_ignored(monkeypatch):
    guard(channelguards.ACCOUNT_AGE, {"min_age_days": 7})
    removed = install_fakes(monkeypatch, account_age, Conn(remaining=None))

    assert account_age.on_message(Ctx(message())) is None
    assert removed == []


def test_account_age_on_message_allowed_member_is_ignored(monkeypatch):
    guard(channelguards.ACCOUNT_AGE, {"min_age_days": 7}, allowed=[USER_ID])
    removed = install_fakes(monkeypatch, account_age, Conn(remaining=3))

    assert account_age.on_message(Ctx(message())) is None
    assert removed == []


def test_readonly_on_message_bot_id_is_ignored(monkeypatch):
    guard(channelguards.READONLY)
    removed = install_fakes(monkeypatch, readonly, Conn())

    assert readonly.on_message(Ctx(message(bot_id="B1"))) is None
    assert removed == []


def test_readonly_on_message_direct_message_is_ignored(monkeypatch):
    guard(channelguards.READONLY)
    channelguards._guards[(channelguards.READONLY, "D1", channelguards.CHANNEL_WIDE)] = channelguards.LiveGuard(7, {}, frozenset())
    removed = install_fakes(monkeypatch, readonly, Conn())

    assert readonly.on_message(Ctx(message(channel="D1"))) is None
    assert removed == []


def test_active_guard_kinds_are_independent():
    guard(channelguards.READONLY)

    assert channelguards.active_guard(CHANNEL_ID, channelguards.SLOWMODE) is None
    assert channelguards.active_guard(CHANNEL_ID, channelguards.READONLY) is not None


def test_days_remaining_sql_falls_back_to_claimed_at():
    sql = account_age.DAYS_REMAINING

    assert "fd.member_joins" in sql
    assert "analytics.dim_member" in sql
    assert "coalesce(j.joined_at, m.claimed_at)" in sql, "a join event must win over the warehouse"


def test_days_remaining_sql_unknown_member_yields_no_row():
    sql = account_age.DAYS_REMAINING

    assert "WHERE join_time.at IS NOT NULL" in sql, "an unknown member yields no row, so the gate opens"
