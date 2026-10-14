import pytest

from bot.nemo import channel, guard_notices

CHANNEL_ID = "C1"
LOG = "CLOG"
BOT = "U9"
THREAD_TS = "1700000000.000100"


def event(event_id, verb="deleted", subject=BOT, label="spammer", text="buy now", detail=None,
          message_ts="1700000000.000200"):
    return (event_id, CHANNEL_ID, subject, verb, label, text, message_ts, f"https://link/{event_id}",
            "A1", detail)


def as_dict(row):
    return dict(zip(("id", "channel_id", "subject_id", "verb", "label", "message_text",
                     "message_ts", "permalink", "app_id", "detail"), row))


class Conn:
    def __init__(self, groups=(), claims=(), thread=None, totals=None, attempts=1):
        self.groups = list(groups)
        self.claims = [list(one) for one in claims]
        self.thread = thread
        self.totals = totals
        self.attempts = attempts
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        self.last = (sql, args)
        return self

    def fetchone(self):
        sql, args = self.last
        if "FROM fd.channel_guard_notice_threads" in sql:
            return self.thread
        if "INSERT INTO fd.channel_guard_notice_threads" in sql:
            return (11,)
        if "UPDATE fd.channel_guard_notice_threads" in sql:
            if self.totals is not None:
                return self.totals
            return (args[0], args[1])
        return (1,)

    def fetchall(self):
        sql, args = self.last
        if "GROUP BY guard_id, subject_id" in sql:
            return self.groups
        if "FOR UPDATE SKIP LOCKED" in sql:
            return self.claims.pop(0) if self.claims else []
        if "notice_attempts = notice_attempts + 1" in sql:
            return [(one, self.attempts) for one in args[0]]
        return []

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class _conn_context:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *failure):
        return False


class Slack:
    def __init__(self, fail_post_at=None, fail_update=False):
        self.fail_post_at = fail_post_at
        self.fail_update = fail_update
        self.posted = []
        self.updated = []

    def chat_postMessage(self, **kwargs):
        if self.fail_post_at is not None and len(self.posted) == self.fail_post_at:
            raise RuntimeError("slack is down")
        self.posted.append(kwargs)
        return {"ok": True, "ts": THREAD_TS}

    def chat_update(self, **kwargs):
        if self.fail_update:
            raise RuntimeError("slack is down")
        self.updated.append(kwargs)
        return {"ok": True}


@pytest.fixture(autouse=True)
def log_channel(monkeypatch):
    monkeypatch.setattr(channel, "internal_log_channel", lambda conn=None: LOG)


def run_drain(monkeypatch, conn, client):
    monkeypatch.setattr(guard_notices, "session", lambda: _conn_context(conn))
    return guard_notices.drain(client)


def test_a_burst_opens_one_parent_with_every_message_under_it(monkeypatch):
    events = [event(n) for n in range(1, 11)]
    conn, client = Conn(groups=[(7, BOT)], claims=[events]), Slack()

    run_drain(monkeypatch, conn, client)

    parent, *replies = client.posted
    assert "thread_ts" not in parent
    assert parent["channel"] == LOG
    assert "Deleted 10 messages." in parent["text"]
    assert len(replies) == 10
    assert {one["thread_ts"] for one in replies} == {THREAD_TS}
    assert conn.args_for("INSERT INTO fd.channel_guard_notice_threads") == [(7, BOT, THREAD_TS, 0, 0)]
    assert conn.args_for("UPDATE fd.channel_guard_notice_threads") == [(10, 0, 11)]
    assert conn.args_for("SET noticed_at = now()") == [(list(range(1, 11)),)]
    assert client.updated == []


def test_events_for_an_open_thread_reply_and_update_the_parent(monkeypatch):
    conn = Conn(groups=[(7, BOT)], claims=[[event(1), event(2)]],
                thread=(11, THREAD_TS), totals=(5, 1))
    client = Slack()

    run_drain(monkeypatch, conn, client)

    assert len(client.posted) == 2
    assert {one["thread_ts"] for one in client.posted} == {THREAD_TS}
    assert not conn.args_for("INSERT INTO fd.channel_guard_notice_threads")
    (update,) = client.updated
    assert update["ts"] == THREAD_TS
    assert "Deleted 5 messages." in update["text"]
    assert "Removed from the channel 1 time." in update["text"]


def test_the_thread_lookup_uses_the_idle_timeout_and_max_age(monkeypatch):
    conn = Conn(groups=[(7, BOT)], claims=[[event(1)]])
    run_drain(monkeypatch, conn, Slack())

    (args,) = conn.args_for("FROM fd.channel_guard_notice_threads")
    assert args == (7, BOT, guard_notices.IDLE_TIMEOUT, guard_notices.MAX_AGE)


def test_the_claim_skips_notices_that_were_given_up(monkeypatch):
    conn = Conn(groups=[(7, BOT)], claims=[[event(1)]])
    run_drain(monkeypatch, conn, Slack())

    (args,) = conn.args_for("FOR UPDATE SKIP LOCKED")
    assert args == (7, BOT, guard_notices.GIVE_UP_AFTER, guard_notices.EVENTS_PER_CLAIM)
    (group_args,) = conn.args_for("GROUP BY guard_id, subject_id")
    assert group_args == (guard_notices.GIVE_UP_AFTER, guard_notices.GROUPS_PER_DRAIN)


def test_no_thread_is_opened_when_the_parent_cannot_be_posted(monkeypatch):
    conn = Conn(groups=[(7, BOT)], claims=[[event(1), event(2)]])

    run_drain(monkeypatch, conn, Slack(fail_post_at=0))

    assert not conn.args_for("INSERT INTO fd.channel_guard_notice_threads")
    assert not conn.args_for("SET noticed_at = now()")
    assert conn.args_for("notice_attempts = notice_attempts + 1") == [([1, 2],)]


def test_a_reply_that_fails_leaves_the_rest_for_the_next_drain(monkeypatch):
    conn = Conn(groups=[(7, BOT)], claims=[[event(1), event(2), event(3)]])
    client = Slack(fail_post_at=3)

    run_drain(monkeypatch, conn, client)

    assert conn.args_for("UPDATE fd.channel_guard_notice_threads") == [(2, 0, 11)]
    assert conn.args_for("SET noticed_at = now()") == [([1, 2],)]
    assert conn.args_for("notice_attempts = notice_attempts + 1") == [([3],)]
    (update,) = client.updated
    assert "Deleted 2 messages." in update["text"]


def test_a_notice_is_given_up_after_its_last_attempt(monkeypatch, caplog):
    conn = Conn(groups=[(7, BOT)], claims=[[event(1)]], attempts=guard_notices.GIVE_UP_AFTER)
    caplog.set_level("WARNING", logger="bot.nemo")

    run_drain(monkeypatch, conn, Slack(fail_post_at=0))

    assert any("gave up on the notice for guard event 1" in one.getMessage()
               for one in caplog.records)


def test_a_failed_update_still_marks_the_events_noticed(monkeypatch):
    conn = Conn(groups=[(7, BOT)], claims=[[event(1)]], thread=(11, THREAD_TS), totals=(4, 0))

    run_drain(monkeypatch, conn, Slack(fail_update=True))

    assert conn.args_for("SET noticed_at = now()") == [([1],)]


def test_a_full_claim_is_followed_by_another(monkeypatch):
    monkeypatch.setattr(guard_notices, "EVENTS_PER_CLAIM", 2)
    conn = Conn(groups=[(7, BOT)], claims=[[event(1), event(2)], [event(3)]])
    client = Slack()

    run_drain(monkeypatch, conn, client)

    assert conn.args_for("SET noticed_at = now()") == [([1, 2],), ([3],)]


def test_one_failing_group_does_not_stop_the_others(monkeypatch):
    conn = Conn(groups=[(7, "U1"), (7, "U2")], claims=[[event(1, subject="U1")]])
    calls = []
    original_drain_group = guard_notices.drain_group

    def failing_drain_group(client, guard_id, subject_id):
        calls.append(subject_id)
        if subject_id == "U1":
            raise RuntimeError("boom")
        return original_drain_group(client, guard_id, subject_id)

    monkeypatch.setattr(guard_notices, "drain_group", failing_drain_group)
    run_drain(monkeypatch, conn, Slack())

    assert calls == ["U1", "U2"]


def test_drain_asks_for_another_pass_when_the_group_limit_is_hit(monkeypatch):
    monkeypatch.setattr(guard_notices, "GROUPS_PER_DRAIN", 1)
    conn = Conn(groups=[(7, BOT)], claims=[[event(1)]])

    assert run_drain(monkeypatch, conn, Slack()) is True


def test_details_name_the_member_channel_and_reason():
    deleted = as_dict(event(1))
    kicked = {**deleted, "verb": "kicked", "message_ts": None}
    away_event = {**deleted, "verb": "let_past", "detail": "away", "message_ts": None}

    assert guard_notices.detail_of(deleted).startswith(
        f"Deleted a message from <@{BOT}> in <#{CHANNEL_ID}>, not on the allow list.\n> buy now")
    assert "<https://link/1|Message>" in guard_notices.detail_of(deleted)
    assert guard_notices.detail_of(kicked).startswith(
        f"Removed <@{BOT}> from <#{CHANNEL_ID}>, not on the allow list.")
    assert guard_notices.detail_of(away_event).startswith(
        f"<@{BOT}> joined <#{CHANNEL_ID}> without being on the allow list and could not be removed "
        "(the admin account is not in the channel).")


def test_a_delete_that_was_given_up_says_so():
    let_past_event = as_dict(event(1, verb="let_past", detail="cant_delete_message"))

    text = guard_notices.detail_of(let_past_event)
    assert text.startswith(
        f"Could not delete a message from <@{BOT}> in <#{CHANNEL_ID}> (cant_delete_message).")
    assert "> buy now" in text
    assert "<https://link/1|Message>" in text


def test_notices_wait_for_a_queued_delete():
    from bot.nemo import channelguards

    assert "NOT remove_pending" in channelguards.CLAIM_NOTICES
    assert "NOT remove_pending" in channelguards.NOTICE_GROUPS


def test_a_bot_with_no_user_is_named_by_its_label():
    assert guard_notices.naming("B1", "spammer") == "*spammer*"
    assert guard_notices.naming("B1", None) == "*B1*"
    assert guard_notices.naming(BOT, "spammer") == f"<@{BOT}>"


def test_summary_pluralises():
    assert guard_notices.summary("*x*", CHANNEL_ID, 1, 0) == (
        f"*x* is not on the allow list for <#{CHANNEL_ID}>. Deleted 1 message."
    )
    assert guard_notices.summary("*x*", CHANNEL_ID, 2, 2) == (
        f"*x* is not on the allow list for <#{CHANNEL_ID}>. Deleted 2 messages. "
        "Removed from the channel 2 times."
    )
