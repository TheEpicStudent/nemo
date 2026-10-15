import contextlib
import inspect

import pytest

from bot.nemo import join_requests, loop
from lib.paths import MIGRATIONS_DIR

REQUEST_ID = 5
CHANNEL_ID = "C0PUBLIC"
REQUESTER_ID = "UMODERATOR"


class Conn:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        sql = self.executed[-1][0]
        for marker, row in self.rows.items():
            if marker in sql:
                return row
        return None

    def args_for(self, marker):
        return [args for sql, args in self.executed if marker in sql]


@pytest.fixture
def join_calls(monkeypatch):
    calls = {"joined": [], "noted": [], "conn": None}

    def use_rows(rows):
        calls["conn"] = Conn(rows)

        @contextlib.contextmanager
        def fake_session():
            yield calls["conn"]

        monkeypatch.setattr(join_requests, "session", fake_session)

    monkeypatch.setattr(join_requests.channels, "joinable", lambda conn, channel_id: True)
    monkeypatch.setattr(join_requests.channels, "noted",
                        lambda conn, channel_id, verb, why=None, by=None:
                        calls["noted"].append((channel_id, verb, why, by)))
    calls["use_rows"] = use_rows
    return calls


def finished(calls):
    return calls["conn"].args_for("SET state = %s")


def test_join_request_joins_and_marks_joined(monkeypatch, join_calls):
    join_calls["use_rows"]({"FOR UPDATE SKIP LOCKED": (CHANNEL_ID, REQUESTER_ID)})
    monkeypatch.setattr(join_requests.channels, "join",
                        lambda client, conn, channel_id, by=None:
                        join_calls["joined"].append((channel_id, by)) or True)

    assert join_requests.run(object(), REQUEST_ID) == "joined"
    assert join_calls["joined"] == [(CHANNEL_ID, REQUESTER_ID)]
    assert finished(join_calls) == [("joined", None, REQUEST_ID)]


def test_join_request_refused_keeps_slack_reason(monkeypatch, join_calls):
    join_calls["use_rows"]({"FOR UPDATE SKIP LOCKED": (CHANNEL_ID, REQUESTER_ID),
                            "verb = 'refused'": ("is_archived",)})
    monkeypatch.setattr(join_requests.channels, "join", lambda client, conn, channel_id, by=None: False)

    assert join_requests.run(object(), REQUEST_ID) == "refused"
    assert finished(join_calls) == [("refused", "is_archived", REQUEST_ID)]


def test_join_request_private_channel_needs_invite(monkeypatch, join_calls):
    join_calls["use_rows"]({"FOR UPDATE SKIP LOCKED": (CHANNEL_ID, REQUESTER_ID)})
    monkeypatch.setattr(join_requests.channels, "joinable", lambda conn, channel_id: False)
    monkeypatch.setattr(join_requests.channels, "join",
                        lambda *args, **kwargs: pytest.fail("a private channel is not joined"))

    assert join_requests.run(object(), REQUEST_ID) == "refused"
    assert join_calls["noted"] == [(CHANNEL_ID, "refused", "needs an invite", REQUESTER_ID)]
    assert finished(join_calls) == [("refused", "needs an invite", REQUEST_ID)]


def test_join_request_notify_channel_matches_loop_listener():
    migration = (MIGRATIONS_DIR / "0233_channel_join_requests.sql").read_text()

    assert f"pg_notify('{loop.JOIN_REQUEST}'" in migration
    assert "JOIN_REQUEST," in inspect.getsource(loop.start)


def test_join_request_already_handled_is_skipped(monkeypatch, join_calls):
    join_calls["use_rows"]({})
    monkeypatch.setattr(join_requests.channels, "join",
                        lambda *args, **kwargs: pytest.fail("a handled request is not joined again"))

    assert join_requests.run(object(), REQUEST_ID) is None
    assert finished(join_calls) == []
