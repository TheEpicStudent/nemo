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
EXPIRES_AT = dt.datetime(2026, 3, 10, 12, tzinfo=dt.UTC)


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


def test_taking_one_up_puts_them_out_and_tells_them_where_from(kicks):
    conn, client = Conn(), Slack()
    assert channel_ban.take_up(client, conn, guard())

    assert kicks == [(CHANNEL_ID, USER_ID)]
    assert conn.executed("enforcement_status = 'held'")
    assert "kicked" in conn.verbs()

    text = client.posted[0]["text"]
    assert f"banned from <#{CHANNEL_ID}>" in text
    assert "for being awful" in text
    assert "until 10 Mar" in text


def test_one_it_cannot_put_out_is_not_claimed_as_held(cannot_kick):
    conn, client = Conn(), Slack()
    assert not channel_ban.take_up(client, conn, guard())

    assert conn.executed("enforcement_status = 'failed'")
    assert not conn.executed("enforcement_status = 'held'")
    assert conn.verbs() == ["failed"]
    assert client.posted == [], "nothing is claimed to them that did not happen"


def test_a_channel_nobody_can_be_kicked_from_keeps_the_reason(cannot_kick):
    conn = Conn()
    channel_ban.take_up(Slack(), conn, guard())
    assert "cant_kick_from_general" in conn.args_for("SET enforcement_status = 'failed'")[0][0]


def test_seen_tells_them_inside_the_thread_they_posted_in(kicks, monkeypatch):
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


def test_seen_tells_them_channel_wide_outside_a_thread(kicks, monkeypatch):
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


def test_coming_back_gets_them_put_out_again(kicks):
    conn = Conn()
    assert channel_ban.remove_from_channel(conn, guard())
    assert kicks == [(CHANNEL_ID, USER_ID)]
    assert conn.verbs() == ["kicked"]


def test_ten_returns_in_an_hour_earns_a_reset(kicks, monkeypatch):
    monkeypatch.setattr(channel_ban.notify.privileged, "reset_sessions", lambda user_id: "reset")
    conn = Conn({"kicked": 10, "reset": 0})
    assert channel_ban.reapply(conn, guard(), "coming back")
    assert "reset" in conn.verbs()


def test_nine_returns_does_not(kicks):
    conn = Conn({"kicked": 9, "reset": 0})
    assert not channel_ban.reapply(conn, guard(), "coming back")
    assert "reset" not in conn.verbs()


def test_a_ban_counts_its_own_kicks_not_somebody_elses_deletes(kicks):
    conn = Conn({"kicked": 0, "deleted": 40, "reset": 0})
    assert not channel_ban.reapply(conn, guard(), "coming back")


def test_lifting_does_not_invite_them_back():
    src = (channel_ban.__doc__ or "") + open(channel_ban.__file__).read()
    assert "conversations_invite" not in src
    assert "invite" not in src.replace("invite_the_admin", "")


def test_a_ban_is_only_found_in_the_channel_it_was_made_in():
    memberguards._loaded = True
    memberguards._bans.clear()
    memberguards._bans[(USER_ID, CHANNEL_ID)] = guard()

    assert memberguards.banned(USER_ID, CHANNEL_ID) is not None
    assert memberguards.banned(USER_ID, "CELSEWHERE") is None
    assert memberguards.banned("USOMEBODY", CHANNEL_ID) is None
    memberguards._loaded = False
    memberguards._bans.clear()
