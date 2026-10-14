import pytest

from bot.nemo.enforcement import purge

CHANNEL_ID = "C1"


class Conn:
    def __init__(self, claims=True):
        self.claims = claims
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        sql, _ = self.executed[-1]
        if "SET state = 'running'" in sql:
            return (CHANNEL_ID, 3) if self.claims else None
        return (1,)

    def fetchall(self):
        return []

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class Slack:
    def __init__(self, pages=None, threads=None):
        self.pages = pages or []
        self.threads = threads or {}
        self.history_calls = []
        self.replies_calls = []

    def conversations_history(self, **kwargs):
        self.history_calls.append(kwargs)
        return self.pages.pop(0) if self.pages else {"messages": []}

    def conversations_replies(self, **kwargs):
        self.replies_calls.append(kwargs)
        thread_pages = self.threads.get(kwargs["ts"])
        if isinstance(thread_pages, list):
            return {"messages": thread_pages.pop(0) if thread_pages else []}
        return {"messages": thread_pages or []}


class _conn_context:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *failure):
        return False


def message(ts, text="body a thing", **over):
    return {"ts": ts, "user": "U1", "text": text, **over}


def parent(ts, replies=1, **over):
    return message(ts, thread_ts=ts, reply_count=replies, **over)


@pytest.fixture
def harness(monkeypatch):
    conn = Conn()
    monkeypatch.setattr(purge, "session", lambda: _conn_context(conn))
    removed = []
    monkeypatch.setattr(purge.guard_actions, "remove",
                        lambda _c, channel_id, ts: removed.append((channel_id, ts)))
    return conn, removed


def test_a_purge_that_is_not_claimed_does_nothing(monkeypatch):
    conn = Conn(claims=False)
    monkeypatch.setattr(purge, "session", lambda: _conn_context(conn))

    assert purge.run(Slack(), 7) == 0
    assert not conn.args_for("SET state = 'done'")


def test_the_newest_are_taken_down(harness):
    _conn, removed = harness
    client = Slack(pages=[{"messages": [message("3"), message("2"), message("1")]}])

    assert purge.run(client, 7) == 3
    assert removed == [(CHANNEL_ID, "3"), (CHANNEL_ID, "2"), (CHANNEL_ID, "1")]


def test_what_was_taken_down_is_kept(harness):
    conn, _ = harness
    purge.run(Slack(pages=[{"messages": [message("3", "the thing said")]}]), 7)

    purge_id, channel_id, ts, thread_ts, authors, texts = conn.args_for("fd.purge_items")[0]
    assert (purge_id, channel_id) == (7, CHANNEL_ID)
    assert ts == ["3"]
    assert thread_ts == [None]
    assert authors == ["U1"]
    assert texts == ["the thing said"]


def test_it_stops_at_what_was_asked_for(harness):
    _, removed = harness
    client = Slack(pages=[{"messages": [message(str(n)) for n in range(9)]}])
    purge.run(client, 7)

    assert len(removed) == 3


def test_a_join_notice_is_not_counted(harness):
    _, removed = harness
    client = Slack(pages=[{"messages": [
        message("3", subtype="channel_join"), message("2"), message("1")]}])
    purge.run(client, 7)

    assert removed == [(CHANNEL_ID, "2"), (CHANNEL_ID, "1")]


def test_it_pages_until_it_has_enough(harness):
    _, removed = harness
    client = Slack(pages=[
        {"messages": [message("5")], "response_metadata": {"next_cursor": "more"}},
        {"messages": [message("4")], "response_metadata": {"next_cursor": "more"}},
        {"messages": [message("3")]},
    ])
    purge.run(client, 7)

    assert len(removed) == 3
    assert client.history_calls[1]["cursor"] == "more"


def test_running_out_of_messages_ends_it(harness):
    conn, removed = harness
    purge.run(Slack(pages=[{"messages": [message("1")]}]), 7)

    assert len(removed) == 1
    assert conn.args_for("SET state = 'done'")


def test_a_failure_keeps_what_it_managed(monkeypatch):
    conn = Conn()
    monkeypatch.setattr(purge, "session", lambda: _conn_context(conn))
    removed = []

    def remove(_c, channel_id, ts):
        if ts == "2":
            raise RuntimeError("slack said no")
        removed.append((channel_id, ts))

    monkeypatch.setattr(purge.guard_actions, "remove", remove)
    purge.run(Slack(pages=[{"messages": [message("3"), message("2"), message("1")]}]), 7)

    failed = conn.args_for("state = 'failed'")[0]
    assert failed[0] == 1
    assert "slack said no" in failed[1]
    assert conn.args_for("fd.purge_items")[0][2] == ["3"]


def test_it_never_takes_more_than_the_cap(harness):
    _conn, removed = harness
    client = Slack(pages=[{"messages": [message(str(n)) for n in range(300)]}])
    purge.run(client, 7)

    assert len(removed) <= purge.MOST


def test_a_thread_goes_down_with_its_parent(harness):
    _conn, removed = harness
    client = Slack(
        pages=[{"messages": [parent("3", replies=2)]}],
        threads={"3": [[message("3.1"), message("3.2")], []]},
    )
    purge.run(client, 7)

    assert removed == [(CHANNEL_ID, "3.1"), (CHANNEL_ID, "3.2"), (CHANNEL_ID, "3")]


def test_the_replies_go_before_the_parent(harness):
    _conn, removed = harness
    client = Slack(
        pages=[{"messages": [parent("3")]}],
        threads={"3": [[message("3.1")], []]},
    )
    purge.run(client, 7)

    assert removed[-1] == (CHANNEL_ID, "3")


def test_a_reply_is_kept_against_its_thread(harness):
    conn, _ = harness
    client = Slack(
        pages=[{"messages": [parent("3")]}],
        threads={"3": [[message("3.1", "in the thread")], []]},
    )
    purge.run(client, 7)

    _, _, ts, thread_ts, _, _ = conn.args_for("fd.purge_items")[0]
    assert ts == ["3.1", "3"]
    assert thread_ts == ["3", None]


def test_a_plain_message_is_not_asked_about(harness):
    _conn, _removed = harness
    client = Slack(pages=[{"messages": [message("3")]}])
    purge.run(client, 7)

    assert client.replies_calls == []


def test_replies_posted_mid_purge_are_caught(harness):
    _conn, removed = harness
    client = Slack(
        pages=[{"messages": [parent("3")]}],
        threads={"3": [[message("3.1")], [message("3.2")], []]},
    )
    purge.run(client, 7)

    assert removed == [(CHANNEL_ID, "3.1"), (CHANNEL_ID, "3.2"), (CHANNEL_ID, "3")]


def test_a_thread_beyond_the_ceiling_stops_and_says_so(harness):
    conn, removed = harness
    oversized_thread = [message(f"3.{n}") for n in range(purge.CEILING + 10)]
    client = Slack(pages=[{"messages": [parent("3")]}], threads={"3": [oversized_thread, []]})
    purge.run(client, 7)

    failed = conn.args_for("state = 'failed'")[0]
    assert len(removed) == purge.CEILING
    assert "hang off" in failed[1]


def test_the_count_covers_the_replies_too(harness):
    conn, _ = harness
    client = Slack(
        pages=[{"messages": [parent("3", replies=2), message("2")]}],
        threads={"3": [[message("3.1"), message("3.2")], []]},
    )

    assert purge.run(client, 7) == 4
    assert conn.args_for("SET state = 'done'")[0][0] == 4
