import datetime as dt
import pathlib

import pytest

from bot.nemo import memberguards
from bot.nemo.enforcement import shush


class ConnContext:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc_info):
        return False


class Ctx:
    def __init__(self, event, client=None):
        self.payload = event
        self.client = client or Slack()


def event(**over):
    return {"user": USER_ID, "channel": CHANNEL_ID, "ts": TS, "text": "hey", **over}

USER_ID = "U1"
CHANNEL_ID = "C1"
TS = "1700000000.000100"
EXPIRES_AT = dt.datetime(2099, 3, 10, 12, tzinfo=dt.UTC)


class Conn:
    def __init__(self, counts=None, claims=True):
        self.counts = counts or {}
        self.claims = claims
        self.statements = []

    def execute(self, sql, args=None):
        self.statements.append((sql, args))
        return self

    def fetchone(self):
        sql, args = self.statements[-1]
        if "verb = %s AND at >" in sql:
            return (self.counts.get(args[1], 0),)
        if "enforcement_status = 'held'" in sql:
            return (7,) if self.claims else None
        return (1,)

    def args_for(self, mark):
        return [args for sql, args in self.statements if mark in sql]

    def executed(self, mark):
        return any(mark in sql for sql, _ in self.statements)


class Slack:
    def __init__(self):
        self.posted = []
        self.ephemeral = []

    def chat_postMessage(self, **kwargs):
        self.posted.append(kwargs)
        return {"ts": "9.9"}

    def chat_postEphemeral(self, **kwargs):
        self.ephemeral.append(kwargs)
        return {"ok": True}


def guard(**over):
    row = {"id": 7, "kind": "shush", "subject_id": USER_ID, "channel_id": None,
           "reason": "being awful", "expires_at": EXPIRES_AT}
    row.update(over)
    return row


@pytest.fixture(autouse=True)
def stub_remove(monkeypatch):
    monkeypatch.setattr(shush.guard_actions, "remove", lambda client, channel_id, ts: True)


def test_enforce_new_guard_posts_notice_with_end_date_and_records_notified():
    conn, client = Conn(), Slack()
    assert shush.enforce(client, conn, guard())

    posted = client.posted[0]
    assert posted["channel"] == USER_ID
    assert "you've been shushed for being awful" in posted["text"]
    assert "until 10 Mar" in posted["text"]
    assert conn.args_for("INSERT INTO fd.member_guard_events")[0][3] == "notified"


def test_enforce_guard_without_expiry_notice_says_no_end_date():
    client = Slack()
    shush.enforce(client, Conn(), guard(expires_at=None))
    assert "with no end date" in client.posted[0]["text"]


def test_enforce_unclaimed_guard_does_not_notify():
    client = Slack()
    assert not shush.enforce(client, Conn(claims=False), guard())
    assert client.posted == []


def test_remove_success_records_deleted_event_and_updates_enforcement_status():
    conn = Conn()
    assert shush.remove(Slack(), conn, guard(), CHANNEL_ID, TS)

    assert conn.executed("enforcement_status = 'held'")
    recorded = conn.args_for("INSERT INTO fd.member_guard_events")[0]
    assert recorded[3] == "deleted"
    assert recorded[4] == TS


def test_on_message_shushed_user_in_thread_posts_ephemeral_in_thread(monkeypatch):
    monkeypatch.setattr(shush, "session", lambda: ConnContext(Conn()))
    monkeypatch.setattr(shush.channel, "firehouse_channel", lambda: "COTHER")
    memberguards._shushes[USER_ID] = guard()
    memberguards._loaded = True
    try:
        client = Slack()
        shush.on_message(Ctx(event(thread_ts="1700000000.000000"), client))
        assert client.ephemeral[0]["thread_ts"] == "1700000000.000000"
    finally:
        memberguards._shushes.clear()
        memberguards._loaded = False


def test_on_message_shushed_user_outside_thread_posts_ephemeral_without_thread_ts(monkeypatch):
    monkeypatch.setattr(shush, "session", lambda: ConnContext(Conn()))
    monkeypatch.setattr(shush.channel, "firehouse_channel", lambda: "COTHER")
    memberguards._shushes[USER_ID] = guard()
    memberguards._loaded = True
    try:
        client = Slack()
        shush.on_message(Ctx(event(), client))
        assert client.ephemeral[0]["thread_ts"] is None
    finally:
        memberguards._shushes.clear()
        memberguards._loaded = False


def test_remove_failure_records_failed_event_and_status(monkeypatch):
    def failing_remove(client, channel_id, ts):
        raise RuntimeError("channel_not_found")

    monkeypatch.setattr(shush.guard_actions, "remove", failing_remove)
    conn = Conn()
    assert not shush.remove(Slack(), conn, guard(), CHANNEL_ID, TS)

    assert conn.executed("enforcement_status = 'failed'")
    assert conn.args_for("INSERT INTO fd.member_guard_events")[0][3] == "failed"


def test_live_guards_sql_selects_only_live_state():
    assert "state = 'live'" in memberguards.LIVE_GUARDS
    assert "lifting" not in memberguards.LIVE_GUARDS


def test_unenforced_sql_selects_nemo_pending_guards():
    assert "enforced_by = 'nemo'" in memberguards.UNENFORCED
    assert "enforcement_status = 'pending'" in memberguards.UNENFORCED


def test_active_shush_and_active_ban_before_load_return_none():
    memberguards._loaded = False
    assert memberguards.active_shush(USER_ID) is None
    assert memberguards.active_ban(USER_ID, CHANNEL_ID) is None


def test_loop_listens_for_member_guard_notify():
    from bot.nemo import loop

    assert loop.MEMBER_GUARD == "fd_member_guard"
    loop_source = pathlib.Path(loop.__file__).read_text()
    assert "MEMBER_GUARD, APP_SETTING" in loop_source, "the loop must LISTEN for it"
    assert "elif channel_name == MEMBER_GUARD:" in loop_source


def test_member_guards_migration_trigger_notifies_on_insert():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0131_member_guards.sql").read_text()
    assert "AFTER INSERT OR UPDATE OF state, carry, expires_at, case_id OR DELETE" in sql
    assert "pg_notify('fd_member_guard'" in sql
