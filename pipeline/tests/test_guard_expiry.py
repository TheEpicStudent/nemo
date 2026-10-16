import contextlib
import datetime as dt
import threading
import time
from types import SimpleNamespace

import pytest

from bot.core import loops
from bot.nemo import guards, loop, memberguards
from bot.nemo.enforcement import sweep

NOW = dt.datetime(2026, 10, 15, 12, 0, tzinfo=dt.timezone.utc)


class Conn:
    def __init__(self, row=None):
        self.row = row
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append(sql)
        return self

    def fetchone(self):
        return self.row


@contextlib.contextmanager
def session_of(conn):
    yield conn


def cached(monkeypatch, shushes=None, bans=None):
    monkeypatch.setattr(memberguards, "_shushes", shushes or {})
    monkeypatch.setattr(memberguards, "_bans", bans or {})
    monkeypatch.setattr(memberguards, "_loaded", True)


@pytest.mark.parametrize(("expires_at", "in_force"), [
    (None, True),
    (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1), True),
    (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1), False),
])
def test_shushed_skips_expired_guard(monkeypatch, expires_at, in_force):
    guard = {"id": 1, "subject_id": "USUB", "expires_at": expires_at}
    cached(monkeypatch, shushes={"USUB": guard})

    assert (memberguards.shushed("USUB") is guard) is in_force


def test_banned_skips_expired_guard(monkeypatch):
    expired = {"id": 2, "expires_at": dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=1)}
    cached(monkeypatch, bans={("USUB", "C_BANNED"): expired})

    assert memberguards.banned("USUB", "C_BANNED") is None


def test_in_force_compares_against_given_time():
    guard = {"expires_at": NOW}

    assert memberguards.in_force(guard, now=NOW - dt.timedelta(seconds=1)) is True
    assert memberguards.in_force(guard, now=NOW) is False


def test_active_thread_guard_query_skips_expired_lock():
    assert "AND (expires_at IS NULL OR expires_at > now())" in guards.ACTIVE_ON_THREAD


def test_next_expiry_reads_member_guards_thread_locks_and_channel_guards():
    assert "FROM fd.member_guards" in sweep.NEXT_EXPIRY
    assert "FROM fd.thread_guards" in sweep.NEXT_EXPIRY
    assert "kind = 'lock' AND state IN ('warned', 'running')" in sweep.NEXT_EXPIRY
    assert "FROM fd.channel_guards" in sweep.NEXT_EXPIRY


@pytest.mark.parametrize(("row", "seconds"), [((12.5,), 12.5), ((None,), None), (None, None)])
def test_seconds_to_next_expiry_reads_epoch(row, seconds):
    assert sweep.seconds_to_next_expiry(Conn(row=row)) == seconds


def test_lift_due_lifts_lapsed_guards_expired_locks_and_channel_guards(monkeypatch):
    lifted = []
    monkeypatch.setattr(loop, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(loop.sweep, "sweep_lapsed", lambda client: lifted.append("member guards"))
    monkeypatch.setattr(loop.guards, "lifting", lambda conn: [7, 8])
    monkeypatch.setattr(loop.guard_actions, "lift_lock", lambda client, guard_id: lifted.append(guard_id))
    monkeypatch.setattr(loop.channelguards, "lift_lapsed",
                        lambda conn: lifted.append("channel guards") or [(9, "slowmode", "C1", "1.0")])
    monkeypatch.setattr(loop.channelguards, "refresh", lambda conn: lifted.append("refreshed"))
    monkeypatch.setattr(loop.sweep, "seconds_to_next_expiry", lambda conn: 42.0)

    assert loop.lift_due(object()) == 42.0
    assert lifted == ["member guards", 7, 8, "channel guards", "refreshed"]


def run_timed(work, **timing):
    stopping = threading.Event()
    wake = loops.timed("test", work, stopping, **timing)
    return stopping, wake


def wait_for(condition, seconds=2.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_timed_runs_again_after_returned_seconds():
    calls = []
    stopping, _ = run_timed(lambda: calls.append(time.monotonic()) or 0.05, longest=5.0, retry=5.0)

    try:
        assert wait_for(lambda: len(calls) >= 3)
    finally:
        stopping.set()


def test_timed_without_expiry_waits_until_woken():
    calls = []
    stopping, wake = run_timed(lambda: calls.append(1) and None, longest=5.0, retry=5.0, settle=0.0)

    try:
        assert wait_for(lambda: len(calls) == 1)
        time.sleep(0.1)
        assert len(calls) == 1
        wake()
        assert wait_for(lambda: len(calls) == 2)
    finally:
        stopping.set()
        wake()


@pytest.mark.parametrize("outcome", [0.0, -3.0, "raise"])
def test_timed_overdue_or_failing_run_waits_retry(outcome):
    calls = []

    def work():
        calls.append(time.monotonic())
        if outcome == "raise":
            raise RuntimeError("slack is down")
        return outcome

    stopping, wake = run_timed(work, longest=5.0, retry=0.2)

    try:
        assert wait_for(lambda: len(calls) >= 2)
        assert calls[1] - calls[0] >= 0.15
    finally:
        stopping.set()
        wake()


def notify_handler(monkeypatch):
    woken, watched = [], {}
    monkeypatch.setattr(loop, "session", lambda: session_of(Conn()))
    for module in (loop.guards, loop.channelguards, loop.memberguards, loop.automod,
                   loop.responses, loop.screening, loop.categories):
        monkeypatch.setattr(module, "refresh", lambda conn: 0)
    monkeypatch.setattr(loop.channel, "refresh_channels", lambda conn: None)
    monkeypatch.setattr(loop.purge, "requeue_stranded", lambda conn: [])
    monkeypatch.setattr(loop.loops, "draining", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop.loops, "watching",
                        lambda name, names, on_notify, stopping: watched.update(on_notify=on_notify))
    monkeypatch.setattr(loop.loops, "sweeping", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop.loops, "timed", lambda *args, **kwargs: (lambda: woken.append(1)))
    monkeypatch.setattr(loop.guard_actions, "run_destroy", lambda client, payload: None)
    monkeypatch.setattr(loop.guard_actions, "after_guard_change", lambda client, payload: None)
    monkeypatch.setattr(loop, "seat_and_announce", lambda client, channel_id: None)

    loop.start(SimpleNamespace(client=None), threading.Event())
    return watched["on_notify"], woken


@pytest.mark.parametrize("channel_name", [loop.MEMBER_GUARD, loop.GUARD, loop.CHANNEL_GUARD])
def test_guard_notify_wakes_lapse_timer(monkeypatch, channel_name):
    on_notify, woken = notify_handler(monkeypatch)

    on_notify(channel_name, "7")

    assert woken == [1]
