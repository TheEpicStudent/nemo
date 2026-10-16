import datetime as dt

import pytest

from bot.nemo import userbots
from bot.nemo.enforcement import notify

USER_ID = "U1"
CHANNEL_ID = "C1"
TS = "1700000000.000100"
EXPIRES_AT = dt.datetime(2026, 3, 10, 23, 59, 59, tzinfo=dt.UTC)


class Conn:
    def __init__(self, counts=None):
        self.counts = counts or {}
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        args = self.executed[-1][1]
        if "verb = %s AND at >" in self.executed[-1][0]:
            return (self.counts.get(args[1], 0),)
        return (1,)

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class Slack:
    def __init__(self, fails=(), users=None):
        self.posted = []
        self.ephemeral = []
        self.fails = fails
        self.users = users or {}
        self.user_lookups = []

    def users_info(self, user):
        self.user_lookups.append(user)
        if user not in self.users:
            raise RuntimeError("user_not_found")
        return {"user": self.users[user]}

    def chat_postMessage(self, **kwargs):
        if "dm" in self.fails:
            raise RuntimeError("cannot dm them")
        self.posted.append(kwargs)
        return {"ts": "9.9"}

    def chat_postEphemeral(self, **kwargs):
        if "post_ephemeral" in self.fails:
            raise RuntimeError("not in channel")
        self.ephemeral.append(kwargs)
        return {"ok": True}


def guard(**overrides):
    row = {"id": 7, "kind": "shush", "subject_id": USER_ID, "channel_id": None,
           "reason": "being awful", "expires_at": EXPIRES_AT}
    row.update(overrides)
    return row


def event(**overrides):
    row = {"channel": CHANNEL_ID, "user": USER_ID, "ts": TS, "subtype": None}
    row.update(overrides)
    return row


def test_ending_with_expires_at_time_formats_utc_datetime():
    assert notify.ending(guard(expires_at=dt.datetime(2026, 3, 10, 14, 30, tzinfo=dt.UTC))) == \
        "until 10 Mar, 14:30 UTC"


def test_ending_formats_end_of_day_as_date_and_none_as_endless():
    assert notify.ending(guard()) == "until 10 Mar"
    assert notify.ending(guard(expires_at=None)) == "with no end date"


@pytest.fixture(autouse=True)
def no_cached_users(monkeypatch):
    monkeypatch.setattr(userbots, "_users", {})


def test_message_target_plain_message_returns_channel_user_ts():
    assert notify.message_target(event(), Slack()) == (CHANNEL_ID, USER_ID, TS)


def test_message_target_direct_message_channel_returns_none():
    assert notify.message_target(event(channel="D1"), Slack())[0] is None


def test_message_target_plain_post_does_not_look_up_user():
    client = Slack()

    notify.message_target(event(), client)

    assert client.user_lookups == []


def test_message_target_bot_user_post_returns_none():
    client = Slack(users={USER_ID: {"id": USER_ID, "is_bot": True}})

    assert notify.message_target(event(bot_id="B1"), client)[0] is None


def test_message_target_user_token_post_returns_target():
    client = Slack(users={USER_ID: {"id": USER_ID, "is_bot": False}})

    assert notify.message_target(event(bot_id="B1"), client) == (CHANNEL_ID, USER_ID, TS)


def test_message_target_user_lookup_failure_returns_none():
    assert notify.message_target(event(bot_id="B1"), Slack())[0] is None


def test_message_target_repeated_post_looks_up_user_once():
    client = Slack(users={USER_ID: {"id": USER_ID, "is_bot": False}})

    notify.message_target(event(bot_id="B1"), client)
    notify.message_target(event(bot_id="B1"), client)

    assert client.user_lookups == [USER_ID]


def test_message_target_non_message_subtype_returns_none():
    for subtype in ("channel_join", "message_deleted", "message_changed", "bot_message"):
        assert notify.message_target(event(subtype=subtype), Slack())[0] is None, subtype


def test_message_target_handled_subtype_returns_channel():
    for subtype in (None, "file_share", "thread_broadcast", "me_message"):
        assert notify.message_target(event(subtype=subtype), Slack())[0] == CHANNEL_ID, subtype


def test_dm_subject_posts_dm_and_records_notified_event():
    conn, client = Conn(), Slack()
    notify.dm_subject(client, conn, guard(), "you've been shushed")
    assert client.posted[0]["channel"] == USER_ID
    assert conn.args_for("INSERT INTO fd.member_guard_events")[0][3] == "notified"


def test_dm_subject_with_dm_failure_records_could_not_notify_detail():
    conn = Conn()
    notify.dm_subject(Slack(fails=("dm",)), conn, guard(), "anything")
    assert conn.args_for("INSERT INTO fd.member_guard_events")[0][6].startswith("could not notify")


def test_post_ephemeral_with_failure_does_not_raise():
    notify.post_ephemeral(Slack(fails=("post_ephemeral",)), CHANNEL_ID, USER_ID, "anything")


def test_should_reset_sessions_with_ten_events_in_window_returns_true():
    assert notify.should_reset_sessions(Conn({"deleted": 10, "reset": 0}), guard(), "deleted")


def test_should_reset_sessions_with_nine_events_in_window_returns_false():
    assert not notify.should_reset_sessions(Conn({"deleted": 9, "reset": 0}), guard(), "deleted")


def test_should_reset_sessions_with_recent_reset_returns_false():
    assert not notify.should_reset_sessions(Conn({"deleted": 40, "reset": 1}), guard(), "deleted")


def test_should_reset_sessions_counts_each_verb_separately():
    counts_conn = Conn({"deleted": 10, "kicked": 0, "reset": 0})
    assert notify.should_reset_sessions(counts_conn, guard(), "deleted")
    assert not notify.should_reset_sessions(counts_conn, guard(), "kicked")


def test_should_reset_sessions_counts_events_in_one_hour_window():
    conn = Conn({"deleted": 10, "reset": 0})
    notify.should_reset_sessions(conn, guard(), "deleted")
    assert all(args[2] == "1 hour" for args in conn.args_for("verb = %s AND at >"))


def test_reset_records_event_with_reset_sessions_outcome(monkeypatch):
    monkeypatch.setattr(notify.privileged, "reset_sessions", lambda user_id, conn=None: "reset")
    conn = Conn()
    assert notify.reset(conn, guard(), "posting") == "reset"
    recorded = conn.args_for("INSERT INTO fd.member_guard_events")[0]
    assert recorded[3] == "reset"
    assert recorded[6] == "reset"
