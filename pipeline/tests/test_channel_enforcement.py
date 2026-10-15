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
def clean(monkeypatch):
    monkeypatch.setattr(userbots, "_people", {})
    channelguards._guards.clear()
    channelguards._loaded = False
    yield
    channelguards._guards.clear()
    channelguards._loaded = False


def guard(kind, settings=None, allowed=()):
    channelguards._guards[(kind, CHANNEL_ID)] = channelguards.LiveGuard(7, settings or {}, frozenset(allowed))
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


def test_nothing_is_read_before_the_cache_is_loaded():
    assert channelguards.guarding(CHANNEL_ID, channelguards.READONLY) is None
    assert channelguards.lets_past(CHANNEL_ID, USER_ID, kind=channelguards.READONLY)


def test_readonly_removes_a_top_level_message(monkeypatch):
    guard(channelguards.READONLY)
    conn = Conn()
    removed = install_fakes(monkeypatch, readonly, conn)
    client = Slack()

    assert readonly.on_message(Ctx(message(), client)) is True
    assert removed == [(CHANNEL_ID, TS)]
    assert conn.args_for("INSERT INTO fd.channel_guard_events")


def test_readonly_user_token_post_is_removed(monkeypatch):
    guard(channelguards.READONLY)
    removed = install_fakes(monkeypatch, readonly, Conn())
    client = Slack(users={USER_ID: {"is_bot": False}})

    assert readonly.on_message(Ctx(message(bot_id="B1"), client)) is True
    assert removed == [(CHANNEL_ID, TS)]


def test_readonly_bot_user_post_is_left_alone(monkeypatch):
    guard(channelguards.READONLY)
    removed = install_fakes(monkeypatch, readonly, Conn())
    client = Slack(users={USER_ID: {"is_bot": True}})

    assert readonly.on_message(Ctx(message(bot_id="B1"), client)) is None
    assert removed == []


def test_readonly_exempt_member_post_is_left_alone(monkeypatch):
    guard(channelguards.READONLY)
    conn = Conn(exempt=True)
    removed = install_fakes(monkeypatch, readonly, conn)

    assert readonly.on_message(Ctx(message())) is None
    assert removed == []
    assert conn.args_for(exemptions.EXEMPT) == [(USER_ID, exemptions.STAFF, USER_ID)]


def test_readonly_echoes_the_message_back(monkeypatch):
    guard(channelguards.READONLY)
    client = Slack()
    install_fakes(monkeypatch, readonly, Conn())
    readonly.on_message(Ctx(message("the thing I typed"), client))

    assert "the thing I typed" in client.ephemeral[0]["text"]


def test_readonly_leaves_a_thread_reply_alone(monkeypatch):
    guard(channelguards.READONLY)
    conn = Conn()
    removed = install_fakes(monkeypatch, readonly, conn)

    assert readonly.on_message(Ctx(message(thread_ts=THREAD))) is None
    assert removed == []


def test_readonly_catches_a_thread_broadcast(monkeypatch):
    guard(channelguards.READONLY)
    removed = install_fakes(monkeypatch, readonly, Conn())
    readonly.on_message(Ctx(message(thread_ts=THREAD, subtype="thread_broadcast")))

    assert removed == [(CHANNEL_ID, TS)]


def test_readonly_also_catches_a_thread_reply_when_told_to(monkeypatch):
    guard(channelguards.READONLY, {"threads": True})
    removed = install_fakes(monkeypatch, readonly, Conn())

    assert readonly.on_message(Ctx(message(thread_ts=THREAD))) is True
    assert removed == [(CHANNEL_ID, TS)]


def test_readonly_lets_an_allowed_member_post(monkeypatch):
    guard(channelguards.READONLY, allowed=[USER_ID])
    removed = install_fakes(monkeypatch, readonly, Conn())

    assert readonly.on_message(Ctx(message())) is None
    assert removed == []


def test_readonly_records_nothing_when_the_removal_fails(monkeypatch):
    guard(channelguards.READONLY)
    conn = Conn()
    install_fakes(monkeypatch, readonly, conn, removes=False)

    assert readonly.on_message(Ctx(message())) is None
    assert not conn.args_for("INSERT INTO fd.channel_guard_events")


def test_slowmode_lets_the_first_message_through(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    conn = Conn(tick=("now",))
    removed = install_fakes(monkeypatch, slowmode, conn)

    assert slowmode.on_message(Ctx(message())) is None
    assert removed == []


def test_slowmode_removes_one_that_is_too_soon(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    conn = Conn(tick=None, remaining=12)
    removed = install_fakes(monkeypatch, slowmode, conn)
    client = Slack()

    assert slowmode.on_message(Ctx(message(), client)) is True
    assert removed == [(CHANNEL_ID, TS)]
    assert "12 seconds" in client.ephemeral[0]["text"]


def test_slowmode_exempt_member_post_skips_clock(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    conn = Conn(tick=None, remaining=12, exempt=True)
    removed = install_fakes(monkeypatch, slowmode, conn)

    assert slowmode.on_message(Ctx(message())) is None
    assert removed == []
    assert not conn.args_for("INSERT INTO fd.slowmode_clock")


def test_slowmode_skips_threads_unless_it_is_told_to(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    removed = install_fakes(monkeypatch, slowmode, Conn(tick=None, remaining=5))

    assert slowmode.on_message(Ctx(message(thread_ts=THREAD))) is None
    assert removed == []


def test_slowmode_keys_a_thread_on_its_own_clock(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30, "threads": True})
    conn = Conn(tick=None, remaining=5)
    install_fakes(monkeypatch, slowmode, conn)
    slowmode.on_message(Ctx(message(thread_ts=THREAD)))

    assert conn.args_for("INSERT INTO fd.slowmode_clock")[0][1] == THREAD


def test_slowmode_tells_them_inside_the_thread_they_posted_in(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30, "threads": True})
    conn = Conn(tick=None, remaining=5)
    install_fakes(monkeypatch, slowmode, conn)
    client = Slack()

    slowmode.on_message(Ctx(message(thread_ts=THREAD), client))

    assert client.ephemeral[0]["thread_ts"] == THREAD


def test_slowmode_tells_them_channel_wide_outside_a_thread(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    conn = Conn(tick=None, remaining=5)
    install_fakes(monkeypatch, slowmode, conn)
    client = Slack()

    slowmode.on_message(Ctx(message(), client))

    assert client.ephemeral[0]["thread_ts"] is None


def test_slowmode_keys_a_channel_message_on_the_empty_thread(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30})
    conn = Conn(tick=("now",))
    install_fakes(monkeypatch, slowmode, conn)
    slowmode.on_message(Ctx(message()))

    assert conn.args_for("INSERT INTO fd.slowmode_clock")[0][1] == ""


def test_slowmode_lets_an_exempt_member_post(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 30}, allowed=[USER_ID])
    removed = install_fakes(monkeypatch, slowmode, Conn(tick=None, remaining=5))

    assert slowmode.on_message(Ctx(message())) is None
    assert removed == []


def test_slowmode_with_no_interval_does_nothing(monkeypatch):
    guard(channelguards.SLOWMODE, {"seconds": 0})
    removed = install_fakes(monkeypatch, slowmode, Conn(tick=None, remaining=5))

    assert slowmode.on_message(Ctx(message())) is None
    assert removed == []


def test_the_wait_reads_in_minutes_once_it_is_long():
    assert slowmode.time_left(45) == "45 seconds"
    assert slowmode.time_left(1) == "1 second"
    assert slowmode.time_left(90) == "2 minutes"


def test_account_age_removes_a_member_who_is_too_new(monkeypatch):
    guard(channelguards.ACCOUNT_AGE, {"min_age_days": 7})
    conn = Conn(remaining=3)
    removed = install_fakes(monkeypatch, account_age, conn)
    client = Slack()

    assert account_age.on_message(Ctx(message(), client)) is True
    assert removed == [(CHANNEL_ID, TS)]
    assert "3 days" in client.ephemeral[0]["text"]


def test_account_age_exempt_member_post_is_left_alone(monkeypatch):
    guard(channelguards.ACCOUNT_AGE, {"min_age_days": 7})
    conn = Conn(remaining=3, exempt=True)
    removed = install_fakes(monkeypatch, account_age, conn)

    assert account_age.on_message(Ctx(message())) is None
    assert removed == []


def test_account_age_lets_an_old_enough_member_post(monkeypatch):
    guard(channelguards.ACCOUNT_AGE, {"min_age_days": 7})
    removed = install_fakes(monkeypatch, account_age, Conn(remaining=None))

    assert account_age.on_message(Ctx(message())) is None
    assert removed == []


def test_account_age_lets_a_member_we_never_saw_join_post(monkeypatch):
    guard(channelguards.ACCOUNT_AGE, {"min_age_days": 7})
    removed = install_fakes(monkeypatch, account_age, Conn(remaining=None))

    assert account_age.on_message(Ctx(message())) is None
    assert removed == []


def test_account_age_lets_an_exempt_member_post(monkeypatch):
    guard(channelguards.ACCOUNT_AGE, {"min_age_days": 7}, allowed=[USER_ID])
    removed = install_fakes(monkeypatch, account_age, Conn(remaining=3))

    assert account_age.on_message(Ctx(message())) is None
    assert removed == []


def test_a_carrier_ignores_a_bot(monkeypatch):
    guard(channelguards.READONLY)
    removed = install_fakes(monkeypatch, readonly, Conn())

    assert readonly.on_message(Ctx(message(bot_id="B1"))) is None
    assert removed == []


def test_a_carrier_ignores_a_direct_message(monkeypatch):
    guard(channelguards.READONLY)
    channelguards._guards[(channelguards.READONLY, "D1")] = channelguards.LiveGuard(7, {}, frozenset())
    removed = install_fakes(monkeypatch, readonly, Conn())

    assert readonly.on_message(Ctx(message(channel="D1"))) is None
    assert removed == []


def test_kinds_do_not_read_each_others_guards():
    guard(channelguards.READONLY)

    assert channelguards.guarding(CHANNEL_ID, channelguards.SLOWMODE) is None
    assert channelguards.guarding(CHANNEL_ID, channelguards.READONLY) is not None


def test_account_age_falls_back_to_when_the_account_was_claimed():
    sql = account_age.DAYS_REMAINING

    assert "fd.member_joins" in sql
    assert "analytics.dim_member" in sql
    assert "coalesce(j.joined_at, m.claimed_at)" in sql, "a join event must win over the warehouse"


def test_account_age_asks_nothing_of_a_member_neither_source_knows():
    sql = account_age.DAYS_REMAINING

    assert "WHERE known.at IS NOT NULL" in sql, "an unknown member yields no row, so the gate opens"
