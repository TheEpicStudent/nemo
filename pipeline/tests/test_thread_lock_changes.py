import contextlib
import datetime as dt

import pytest

from bot.core.formatting import short_end
from bot.nemo import guard_actions, guards
from bot.nemo.surface import thread_destroy, thread_lock
from bot.nemo.views import guard as card
from bot.nemo.views import lengths

CHANNEL_ID = "C1"
THREAD = "1700000000.000000"
MOD = "UMOD"
NOW = dt.datetime(2026, 10, 16, 9, 30, tzinfo=dt.UTC)
END = dt.datetime(2026, 10, 17, 14, 30, tzinfo=dt.UTC)


def lock_row(**over):
    row = {"id": 5, "kind": guards.LOCK, "opened_by": MOD, "expires_at": END, "reason": "Heated argument",
           "warned_ts": "1700000000.000500"}
    row.update(over)
    return row


def values(**over):
    row = {"reason": "Heated argument", "starting": True, "duration": None, "extend": None, "until": None,
           "note": False, "note_body": None}
    row.update(over)
    return row


def block_ids(view):
    return [block.get("block_id") for block in view["blocks"]]


def test_lock_view_has_optional_duration_and_reason_blocks():
    view = card.lock_view(CHANNEL_ID, THREAD)

    assert block_ids(view) == [card.LOCK_DURATION, card.REASON]
    assert view["blocks"][0]["optional"] is True
    assert view["blocks"][0]["element"]["placeholder"]["text"] == "No end"
    assert view["submit"]["text"] == "Lock"


def test_lock_view_custom_adds_until_block():
    assert block_ids(card.lock_view(CHANNEL_ID, THREAD, custom=True)) == [card.LOCK_DURATION, card.UNTIL, card.REASON]


def test_locked_view_shows_status_reason_and_required_extend():
    view = card.locked_view(CHANNEL_ID, THREAD, lock_row(), now=NOW)

    assert view["blocks"][0]["text"]["text"] == (
        f"*Locked* until {short_end(END)} (1d 5h left) for *Heated argument*, set by <@{MOD}>")
    assert view["blocks"][0]["accessory"]["action_id"] == card.UNLOCK
    assert view["blocks"][1]["block_id"] == card.LOCK_EXTEND
    assert view["blocks"][1]["optional"] is False
    assert view["submit"]["text"] == "Save"


def test_submitted_values_lock_picker_returns_duration_and_reason():
    state = {"values": {
        card.LOCK_DURATION: {card.LOCK_DURATION: {"selected_option": {"value": "2h"}}},
        card.REASON: {card.REASON: {"value": " raid "}},
    }}

    picked = card.submitted_values(state)

    assert (picked["starting"], picked["duration"], picked["reason"], picked["until"]) == (True, "2h", "raid", None)


@pytest.mark.parametrize(("over", "errors"), [
    ({}, None),
    ({"reason": ""}, {card.REASON: "Add a reason."}),
    ({"duration": lengths.CUSTOM}, {card.UNTIL: "Select the end."}),
    ({"duration": lengths.CUSTOM, "until": NOW - dt.timedelta(minutes=1)},
     {card.UNTIL: "Select a time in the future."}),
    ({"starting": False, "reason": ""}, {card.LOCK_EXTEND: "Select how long to extend."}),
    ({"starting": False, "reason": "", "extend": "1h"}, None),
])
def test_lock_errors_validates_reason_extend_and_end(over, errors):
    assert card.lock_errors(values(**over), NOW) == errors


@pytest.mark.parametrize(("over", "current", "expected"), [
    ({}, None, None),
    ({"duration": "1h"}, None, NOW + dt.timedelta(hours=1)),
    ({"duration": lengths.CUSTOM, "until": END}, None, END),
    ({"starting": False, "extend": "2h"}, lock_row(), END + dt.timedelta(hours=2)),
    ({"starting": False, "extend": "30m"}, lock_row(expires_at=None), NOW + dt.timedelta(minutes=30)),
])
def test_lock_end_starts_now_or_extends_current_end(over, current, expected):
    assert card.lock_end(values(**over), current, NOW) == expected


class Client:
    def __init__(self, delete_error=None):
        self.delete_error = delete_error
        self.opened = []
        self.updated = []
        self.deleted = []

    def views_open(self, **kwargs):
        self.opened.append(kwargs)

    def views_update(self, **kwargs):
        self.updated.append(kwargs)

    def chat_delete(self, **kwargs):
        if self.delete_error:
            raise RuntimeError(self.delete_error)
        self.deleted.append(kwargs)


class SurfaceCtx:
    def __init__(self, view=None, client=None):
        self.view = view or {}
        self.client = client or Client()
        self.user_id = MOD
        self.channel_id = CHANNEL_ID
        self.thread_ts = THREAD
        self.trigger_id = "T1"
        self.acked = []
        self.ephemeral_messages = []

    def ack(self, **kwargs):
        self.acked.append(kwargs)

    def join(self, channel_id=None):
        return None

    def post_ephemeral(self, message, channel_id=None, thread_ts=None):
        self.ephemeral_messages.append(message)

    def post_ephemeral_or_dm(self, message, channel_id=None, thread_ts=None):
        self.ephemeral_messages.append(message)


@contextlib.contextmanager
def session_of(conn=None):
    yield conn


def locked_submission(extend="1h"):
    view = card.locked_view(CHANNEL_ID, THREAD, lock_row())
    view.update(id="V1", hash="H1")
    view["state"] = {"values": {card.LOCK_EXTEND: {card.LOCK_EXTEND: {"selected_option": extend and {"value": extend}}}}}
    return view


@pytest.fixture
def live(monkeypatch):
    state = {"row": lock_row(), "extended": [], "lifted": []}
    monkeypatch.setattr(thread_lock, "session", lambda: session_of(object()))
    monkeypatch.setattr(guards, "live_on_thread", lambda conn, channel_id, thread_ts: state["row"])
    monkeypatch.setattr(guards, "extend",
                        lambda conn, current, expires_at, by: state["extended"].append((current["id"], expires_at, by))
                        or current["id"])
    monkeypatch.setattr(guards, "refresh", lambda conn: 0)
    monkeypatch.setattr(guard_actions, "lift_lock",
                        lambda client, guard_id, by=None: state["lifted"].append((guard_id, by)) or guard_id)
    monkeypatch.setattr(guard_actions, "update_lock_notice", lambda client, guard_id: None)
    return state


def test_open_lock_modal_locked_thread_shows_status_view(live):
    ctx = SurfaceCtx()

    thread_lock.open_lock_modal(ctx)

    assert ctx.client.opened[0]["view"]["submit"]["text"] == "Save"


def test_open_lock_modal_destroying_thread_refuses(live):
    live["row"] = lock_row(kind=guards.DESTROY)
    ctx = SurfaceCtx()

    thread_lock.open_lock_modal(ctx)

    assert ctx.client.opened == []
    assert ctx.ephemeral_messages == ["Thread already being destroyed"]


def test_unlock_thread_lifts_lock_and_updates_view(live):
    ctx = SurfaceCtx(locked_submission())

    assert thread_lock.unlock_thread(ctx) == 5
    assert live["lifted"] == [(5, MOD)]
    assert ctx.client.updated[0]["view"]["callback_id"] == card.UNLOCKED_CALLBACK
    assert ctx.ephemeral_messages == ["Thread unlocked"]


def test_submit_lock_extend_moves_end_and_confirms(live):
    ctx = SurfaceCtx(locked_submission("2h"))

    thread_lock.submit_lock(ctx)

    assert live["extended"] == [(5, END + dt.timedelta(hours=2), MOD)]
    assert ctx.ephemeral_messages == []


def test_submit_lock_extend_after_lock_ended_is_refused(live):
    live["row"] = None
    ctx = SurfaceCtx(locked_submission("2h"))

    thread_lock.submit_lock(ctx)

    assert live["extended"] == []
    assert ctx.ephemeral_messages == ["Lock already ended"]


def test_submit_lock_extend_without_choice_acks_errors(live):
    ctx = SurfaceCtx(locked_submission(None))

    thread_lock.submit_lock(ctx)

    assert ctx.acked == [{"response_action": "errors", "errors": {card.LOCK_EXTEND: "Select how long to extend."}}]


def test_reshape_lock_on_duration_custom_adds_until_block(live):
    live["row"] = None
    view = card.lock_view(CHANNEL_ID, THREAD)
    view.update(id="V1", hash="H1")
    view["state"] = {"values": {card.LOCK_DURATION: {card.LOCK_DURATION: {"selected_option": {"value": "custom"}}}}}
    ctx = SurfaceCtx(view)

    thread_lock.reshape_lock_on_duration(ctx)

    assert card.UNTIL in block_ids(ctx.client.updated[0]["view"])


class WarningConn:
    def __init__(self, waiting):
        self.waiting = waiting
        self.removed = []

    def execute(self, sql, args=None):
        if sql == guards.WARNING_REMOVED:
            self.removed.append(args[0])
        return self

    def fetchall(self):
        return self.waiting


@pytest.mark.parametrize(("error", "removed"), [(None, [5]), ("message_not_found", [5]),
                                                ("channel_not_found", [5]), ("ratelimited", [])])
def test_remove_lock_warnings_delete_error_controls_removed_ids(monkeypatch, error, removed):
    conn = WarningConn([(5, CHANNEL_ID, THREAD, "1700000000.000500")])
    monkeypatch.setattr(guard_actions, "session", lambda: session_of(conn))
    client = Client(delete_error=error)

    guard_actions.remove_lock_warnings(client)

    assert conn.removed == removed


def test_warnings_to_remove_sql_selects_ended_locks_with_notice():
    assert "kind = 'lock' AND state IN ('done', 'failed') AND warned_ts IS NOT NULL" in guards.WARNINGS_TO_REMOVE
    assert "warning_removed_at IS NULL" in guards.WARNINGS_TO_REMOVE


def test_destroy_thread_on_locked_thread_finishes_lock_then_opens_destroy(monkeypatch):
    calls = []
    monkeypatch.setattr(thread_destroy, "session", lambda: session_of(object()))
    monkeypatch.setattr(guards, "live_on_thread", lambda conn, channel_id, thread_ts: lock_row())
    monkeypatch.setattr(guards, "finish",
                        lambda conn, guard_id, state, error=None, sha=None, by=None:
                        calls.append(("finish", guard_id, state, by)))
    monkeypatch.setattr(guards, "open_guard", lambda conn, kind, *args: calls.append(("open", kind)) or 6)
    monkeypatch.setattr(guards, "warn", lambda *args: "1.1")
    monkeypatch.setattr(guards, "refresh", lambda conn: 0)
    view = card.destroy_view(CHANNEL_ID, THREAD)
    view["state"] = {"values": {card.REASON: {card.REASON: {"value": "raid"}}}}

    assert thread_destroy.destroy_thread(SurfaceCtx(view)) == 6
    assert calls == [("finish", 5, "done", MOD), ("open", guards.DESTROY)]
