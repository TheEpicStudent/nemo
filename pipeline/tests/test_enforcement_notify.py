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
        self.looked_up = []

    def users_info(self, user):
        self.looked_up.append(user)
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


def guard(**over):
    row = {"id": 7, "kind": "shush", "subject_id": USER_ID, "channel_id": None,
           "reason": "being awful", "expires_at": EXPIRES_AT}
    row.update(over)
    return row


def event(**over):
    row = {"channel": CHANNEL_ID, "user": USER_ID, "ts": TS, "subtype": None}
    row.update(over)
    return row


def test_ending_with_a_time_shows_the_time_in_utc():
    assert notify.ending(guard(expires_at=dt.datetime(2026, 3, 10, 14, 30, tzinfo=dt.UTC))) == \
        "until 10 Mar, 14:30 UTC"


def test_a_date_reads_as_a_date_and_none_says_so():
    assert notify.ending(guard()) == "until 10 Mar"
    assert notify.ending(guard(expires_at=None)) == "with no end date"


@pytest.fixture(autouse=True)
def no_cached_users(monkeypatch):
    monkeypatch.setattr(userbots, "_people", {})


def test_a_message_with_words_in_it_is_ours():
    assert notify.message_target(event(), Slack()) == (CHANNEL_ID, USER_ID, TS)


def test_a_direct_message_is_never_ours():
    assert notify.message_target(event(channel="D1"), Slack())[0] is None


def test_message_target_plain_post_does_not_look_up_user():
    client = Slack()

    notify.message_target(event(), client)

    assert client.looked_up == []


def test_message_target_bot_user_post_is_skipped():
    client = Slack(users={USER_ID: {"id": USER_ID, "is_bot": True}})

    assert notify.message_target(event(bot_id="B1"), client)[0] is None


def test_message_target_user_token_post_is_ours():
    client = Slack(users={USER_ID: {"id": USER_ID, "is_bot": False}})

    assert notify.message_target(event(bot_id="B1"), client) == (CHANNEL_ID, USER_ID, TS)


def test_message_target_user_lookup_failure_is_skipped():
    assert notify.message_target(event(bot_id="B1"), Slack())[0] is None


def test_message_target_user_lookup_is_cached():
    client = Slack(users={USER_ID: {"id": USER_ID, "is_bot": False}})

    notify.message_target(event(bot_id="B1"), client)
    notify.message_target(event(bot_id="B1"), client)

    assert client.looked_up == [USER_ID]


def test_a_subtype_that_carries_nothing_is_skipped():
    for subtype in ("channel_join", "message_deleted", "message_changed", "bot_message"):
        assert notify.message_target(event(subtype=subtype), Slack())[0] is None, subtype


def test_every_subtype_that_carries_words_is_ours():
    for subtype in (None, "file_share", "thread_broadcast", "me_message"):
        assert notify.message_target(event(subtype=subtype), Slack())[0] == CHANNEL_ID, subtype


def test_the_notification_is_written_down():
    conn, client = Conn(), Slack()
    notify.dm_subject(client, conn, guard(), "you've been shushed")
    assert client.posted[0]["channel"] == USER_ID
    assert conn.args_for("INSERT INTO fd.member_guard_events")[0][3] == "notified"


def test_a_dm_that_will_not_send_is_written_down_as_such():
    conn = Conn()
    notify.dm_subject(Slack(fails=("dm",)), conn, guard(), "anything")
    assert conn.args_for("INSERT INTO fd.member_guard_events")[0][6].startswith("could not notify")


def test_a_whisper_that_will_not_send_is_swallowed():
    notify.post_ephemeral(Slack(fails=("post_ephemeral",)), CHANNEL_ID, USER_ID, "anything")


def test_ten_in_an_hour_earns_a_reset():
    assert notify.reset_threshold_met(Conn({"deleted": 10, "reset": 0}), guard(), "deleted")


def test_nine_in_an_hour_does_not():
    assert not notify.reset_threshold_met(Conn({"deleted": 9, "reset": 0}), guard(), "deleted")


def test_one_reset_an_hour_is_enough():
    assert not notify.reset_threshold_met(Conn({"deleted": 40, "reset": 1}), guard(), "deleted")


def test_each_carrier_counts_its_own_verb():
    counts_conn = Conn({"deleted": 10, "kicked": 0, "reset": 0})
    assert notify.reset_threshold_met(counts_conn, guard(), "deleted")
    assert not notify.reset_threshold_met(counts_conn, guard(), "kicked")


def test_the_count_only_looks_back_an_hour():
    conn = Conn({"deleted": 10, "reset": 0})
    notify.reset_threshold_met(conn, guard(), "deleted")
    assert all(args[2] == "1 hour" for args in conn.args_for("verb = %s AND at >"))


def test_a_reset_is_written_down_with_what_came_of_it(monkeypatch):
    monkeypatch.setattr(notify.privileged, "reset_sessions", lambda user_id, conn=None: "reset")
    conn = Conn()
    assert notify.reset(conn, guard(), "posting") == "reset"
    recorded = conn.args_for("INSERT INTO fd.member_guard_events")[0]
    assert recorded[3] == "reset"
    assert recorded[6] == "reset"
