import datetime as dt

import pytest

from bot.nemo import memberguards
from bot.nemo.enforcement import channel_ban


class _conn_context:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *failure):
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
    def __init__(self, counts=None):
        self.counts = counts or {}
        self.statements = []

    def execute(self, sql, args=None):
        self.statements.append((sql, args))
        return self

    def fetchone(self):
        sql, args = self.statements[-1]
        if "verb = %s AND at >" in sql:
            return (self.counts.get(args[1], 0),)
        return (1,)

    def args_for(self, mark):
        return [args for sql, args in self.statements if mark in sql]

    def executed(self, mark):
        return any(mark in sql for sql, _ in self.statements)

    def verbs(self):
        return [args[3] for args in self.args_for("INSERT INTO fd.member_guard_events")]


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
    row = {"id": 7, "kind": "channel_ban", "subject_id": USER_ID, "channel_id": CHANNEL_ID,
           "reason": "being awful", "expires_at": EXPIRES_AT}
    row.update(over)
    return row


@pytest.fixture
def kicks(monkeypatch):
    kick_calls = []

    def kick(channel_id, user_id):
        kick_calls.append((channel_id, user_id))
        return "kicked"

    monkeypatch.setattr(channel_ban.privileged, "kick", kick)
    return kick_calls


@pytest.fixture
def cannot_kick(monkeypatch):
    monkeypatch.setattr(channel_ban.privileged, "kick",
                        lambda channel_id, user_id: "failed: cant_kick_from_general")


def test_enforce_kicks_member_and_posts_notice_with_reason_and_expiry(kicks):
    conn, client = Conn(), Slack()
    assert channel_ban.enforce(client, conn, guard())

    assert kicks == [(CHANNEL_ID, USER_ID)]
    assert conn.executed("enforcement_status = 'held'")
    assert "kicked" in conn.verbs()

    text = client.posted[0]["text"]
    assert f"banned from <#{CHANNEL_ID}>" in text
    assert "for being awful" in text
    assert "until 10 Mar" in text


def test_enforce_failed_kick_marks_failed_without_notice(cannot_kick):
    conn, client = Conn(), Slack()
    assert not channel_ban.enforce(client, conn, guard())

    assert conn.executed("enforcement_status = 'failed'")
    assert not conn.executed("enforcement_status = 'held'")
    assert conn.verbs() == ["failed"]
    assert client.posted == [], "nothing is claimed to them that did not happen"


def test_enforce_unkickable_channel_stores_failure_reason(cannot_kick):
    conn = Conn()
    channel_ban.enforce(Slack(), conn, guard())
    assert "cant_kick_from_general" in conn.args_for("SET enforcement_status = 'failed'")[0][0]


def test_on_message_banned_member_in_thread_sends_ephemeral_in_thread(kicks, monkeypatch):
    monkeypatch.setattr(channel_ban, "session", lambda: _conn_context(Conn()))
    monkeypatch.setattr(channel_ban.guard_actions, "remove", lambda client, channel_id, ts: True)
    memberguards._bans[(USER_ID, CHANNEL_ID)] = guard()
    memberguards._loaded = True
    try:
        client = Slack()
        channel_ban.on_message(Ctx(event(thread_ts="1700000000.000000"), client))
        assert client.ephemeral[0]["thread_ts"] == "1700000000.000000"
    finally:
        memberguards._bans.clear()
        memberguards._loaded = False


def test_on_message_banned_member_outside_thread_sends_channel_ephemeral(kicks, monkeypatch):
    monkeypatch.setattr(channel_ban, "session", lambda: _conn_context(Conn()))
    monkeypatch.setattr(channel_ban.guard_actions, "remove", lambda client, channel_id, ts: True)
    memberguards._bans[(USER_ID, CHANNEL_ID)] = guard()
    memberguards._loaded = True
    try:
        client = Slack()
        channel_ban.on_message(Ctx(event(), client))
        assert client.ephemeral[0]["thread_ts"] is None
    finally:
        memberguards._bans.clear()
        memberguards._loaded = False


def test_kick_from_channel_kicks_member_and_records_kicked_verb(kicks):
    conn = Conn()
    assert channel_ban.kick_from_channel(conn, guard())
    assert kicks == [(CHANNEL_ID, USER_ID)]
    assert conn.verbs() == ["kicked"]


def test_reapply_kick_after_ten_kicks_in_hour_resets_sessions(kicks, monkeypatch):
    monkeypatch.setattr(channel_ban.notify.privileged, "reset_sessions", lambda user_id, conn=None: "reset")
    conn = Conn({"kicked": 10, "reset": 0})
    assert channel_ban.reapply_kick(conn, guard(), "coming back")
    assert "reset" in conn.verbs()


def test_reapply_kick_after_nine_kicks_in_hour_skips_reset(kicks):
    conn = Conn({"kicked": 9, "reset": 0})
    assert not channel_ban.reapply_kick(conn, guard(), "coming back")
    assert "reset" not in conn.verbs()


def test_reapply_kick_counts_kicked_verb_and_ignores_deleted(kicks):
    conn = Conn({"kicked": 0, "deleted": 40, "reset": 0})
    assert not channel_ban.reapply_kick(conn, guard(), "coming back")


def test_channel_ban_module_source_has_no_invite_call():
    src = (channel_ban.__doc__ or "") + open(channel_ban.__file__).read()
    assert "conversations_invite" not in src
    assert "invite" not in src.replace("invite_the_admin", "")


def test_active_ban_matches_only_banned_member_and_channel():
    memberguards._loaded = True
    memberguards._bans.clear()
    memberguards._bans[(USER_ID, CHANNEL_ID)] = guard()

    assert memberguards.active_ban(USER_ID, CHANNEL_ID) is not None
    assert memberguards.active_ban(USER_ID, "CELSEWHERE") is None
    assert memberguards.active_ban("USOMEBODY", CHANNEL_ID) is None
    memberguards._loaded = False
    memberguards._bans.clear()
