import contextlib
import datetime as dt

import pytest

from bot.core import privileged
from bot.core.formatting import short_end
from bot.nemo import guard_actions, guards, userbots
from bot.nemo.surface import thread_watch
from bot.nemo.views import guard as card

CHANNEL_ID = "C1"
THREAD = "1700000000.000000"
TS = "1700000000.000100"
MOD = "UMOD"
USER_ID = "U1"
END = dt.datetime(2026, 10, 17, 14, 30, tzinfo=dt.UTC)


@contextlib.contextmanager
def session_of(conn=None):
    yield conn


def test_lock_notice_shows_end_reason_and_signature():
    notice = card.lock_notice(END, "Heated argument", MOD)

    assert notice["text"] == f"*Thread locked* · ends {short_end(END)} · Reason: Heated argument"
    assert notice["blocks"][1]["elements"][0]["text"] == f"Fire Department · <@{MOD}>"


def test_lock_notice_with_session_reset_on_warns_about_sign_out():
    notice = card.lock_notice(None, "raid", MOD, signs_out=True)

    assert notice["text"] == "*Thread locked* · no end date · Reason: raid"
    assert notice["blocks"][1]["elements"][0]["text"] == \
        f"Fire Department · <@{MOD}> · Repeated replies sign you out of Slack"


@pytest.mark.parametrize(("mode", "warns"), [(privileged.ON, True), (privileged.LOG, False), (privileged.OFF, False)])
def test_guard_actions_lock_notice_follows_session_reset_mode(monkeypatch, mode, warns):
    monkeypatch.setattr(privileged, "mode", lambda conn=None: mode)

    text = guard_actions.lock_notice(object(), END, "raid", MOD)["blocks"][1]["elements"][0]["text"]

    assert text.endswith(card.SIGNS_OUT) is warns


def test_lock_held_back_quotes_the_reply():
    told = card.lock_held_back(END, "but nobody answered")

    assert told["text"] == f"*Thread locked* · ends {short_end(END)}"
    assert told["blocks"][1]["elements"][0]["elements"][0]["text"] == "but nobody answered"


class Slack:
    def __init__(self, react_error=None):
        self.react_error = react_error
        self.posted = []
        self.reacted = []
        self.unreacted = []
        self.updated = []
        self.deleted = []
        self.ephemeral = []

    def chat_postMessage(self, **kwargs):
        self.posted.append(kwargs)
        return {"ts": "1700000000.000500"}

    def reactions_add(self, **kwargs):
        if self.react_error:
            raise RuntimeError(self.react_error)
        self.reacted.append(kwargs)

    def reactions_remove(self, **kwargs):
        self.unreacted.append(kwargs)

    def chat_update(self, **kwargs):
        self.updated.append(kwargs)

    def chat_delete(self, **kwargs):
        self.deleted.append(kwargs)

    def chat_postEphemeral(self, **kwargs):
        self.ephemeral.append(kwargs)


class Conn:
    def __init__(self, waiting=()):
        self.waiting = list(waiting)
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return self.waiting


def test_warn_lock_posts_the_notice_and_marks_the_root():
    client = Slack()
    notice = card.lock_notice(END, "raid", MOD)

    assert guards.warn(client, Conn(), 5, CHANNEL_ID, THREAD, guards.LOCK, notice=notice) == "1700000000.000500"
    assert client.posted[0]["blocks"] == notice["blocks"]
    assert client.reacted == [{"channel": CHANNEL_ID, "timestamp": THREAD, "name": "lock"}]


def test_warn_lock_survives_a_failed_mark():
    client = Slack(react_error="already_reacted")

    assert guards.warn(client, Conn(), 5, CHANNEL_ID, THREAD, guards.LOCK) == "1700000000.000500"


def test_warn_destroy_does_not_mark_the_root():
    client = Slack()

    guards.warn(client, Conn(), 5, CHANNEL_ID, THREAD, guards.DESTROY)

    assert client.reacted == []
    assert client.posted[0]["text"] == guards.WARNING[guards.DESTROY]


def test_remove_lock_warnings_also_removes_the_mark(monkeypatch):
    conn = Conn([(5, CHANNEL_ID, THREAD, "1700000000.000500")])
    monkeypatch.setattr(guard_actions, "session", lambda: session_of(conn))
    client = Slack()

    assert guard_actions.remove_lock_warnings(client) == 1
    assert client.deleted == [{"channel": CHANNEL_ID, "ts": "1700000000.000500"}]
    assert client.unreacted == [{"channel": CHANNEL_ID, "timestamp": THREAD, "name": "lock"}]


def test_update_lock_notice_rewrites_the_notice_with_the_new_end(monkeypatch):
    row = {"channel_id": CHANNEL_ID, "warned_ts": "1700000000.000500", "expires_at": END,
           "reason": "raid", "opened_by": MOD}
    monkeypatch.setattr(guard_actions, "session", lambda: session_of(object()))
    monkeypatch.setattr(guards, "lock_notice_row", lambda conn, guard_id: row)
    monkeypatch.setattr(privileged, "mode", lambda conn=None: privileged.OFF)
    client = Slack()

    assert guard_actions.update_lock_notice(client, 5) == "1700000000.000500"
    assert client.updated[0]["ts"] == "1700000000.000500"
    assert client.updated[0]["text"] == f"*Thread locked* · ends {short_end(END)} · Reason: raid"


def test_update_lock_notice_without_a_live_lock_does_nothing(monkeypatch):
    monkeypatch.setattr(guard_actions, "session", lambda: session_of(object()))
    monkeypatch.setattr(guards, "lock_notice_row", lambda conn, guard_id: None)
    client = Slack()

    assert guard_actions.update_lock_notice(client, 5) is None
    assert client.updated == []


def test_lock_notice_query_takes_only_a_live_posted_lock():
    assert "kind = 'lock' AND state IN ('warned', 'running') AND warned_ts IS NOT NULL" in guards.LOCK_NOTICE


class Ctx:
    def __init__(self, event, client):
        self.payload = event
        self.client = client


@pytest.fixture
def watching(monkeypatch):
    monkeypatch.setattr(userbots, "_people", {})
    monkeypatch.setattr(thread_watch, "session", lambda: session_of(object()))
    monkeypatch.setattr(thread_watch.guards, "watching", lambda channel_id, ts: True)
    monkeypatch.setattr(thread_watch.guards, "exempt", lambda conn, who, by: False)
    monkeypatch.setattr(thread_watch.guard_actions, "note_it", lambda conn, guard, who, ts: True)
    monkeypatch.setattr(thread_watch.guard_actions, "delete_notice", lambda client, guard_id, channel_id, ts: True)
    monkeypatch.setattr(thread_watch.guard_actions, "threshold_met", lambda guard, who: None)

    def guard(kind):
        row = (5, kind, CHANNEL_ID, THREAD, "warned", MOD, "1700000000.000500", END)
        monkeypatch.setattr(thread_watch.guards, "active_guard", lambda conn, channel_id, ts: row)
    return guard


def reply():
    return {"user": USER_ID, "channel": CHANNEL_ID, "ts": TS, "thread_ts": THREAD, "text": "but nobody answered"}


def test_deleted_reply_in_a_lock_tells_the_member_with_their_text(watching):
    watching(guards.LOCK)
    client = Slack()

    thread_watch.watched(Ctx(reply(), client))

    told = client.ephemeral[0]
    assert (told["user"], told["thread_ts"]) == (USER_ID, THREAD)
    assert told["text"] == f"*Thread locked* · ends {short_end(END)}"
    assert told["blocks"][1]["elements"][0]["elements"][0]["text"] == "but nobody answered"


def test_deleted_reply_during_a_destroy_tells_nobody(watching):
    watching(guards.DESTROY)
    client = Slack()

    thread_watch.watched(Ctx(reply(), client))

    assert client.ephemeral == []
