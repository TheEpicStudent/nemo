import contextlib
import threading
from types import SimpleNamespace

import pytest

from bot.nemo import channelguards, channels, loop, responses

FIREHOUSE_ID = "C_FIRE"
PRIVATE_ID = "G_PRIVATE"


class Conn:
    def __init__(self, rows=None, row=None):
        self.rows = rows or []
        self.row = row
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.row


@contextlib.contextmanager
def session_of(conn):
    yield conn


def configure(monkeypatch, configured, inside=(), waiting=(), private=()):
    calls = {"joined": [], "marked": []}
    monkeypatch.setattr(channels, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(channels, "configured_channels", lambda conn: set(configured))
    monkeypatch.setattr(channels, "is_inside", lambda conn, channel_id: channel_id in inside)
    monkeypatch.setattr(channels, "waits_for_invite", lambda conn, channel_id: channel_id in waiting)
    monkeypatch.setattr(channels, "joinable", lambda conn, channel_id: channel_id not in private)
    monkeypatch.setattr(channels, "join", lambda client, conn, channel_id, by=None, verb="joined":
                        calls["joined"].append(channel_id) or True)
    monkeypatch.setattr(channels, "mark_private", lambda client, conn, channel_id, by:
                        calls["marked"].append(channel_id) or False)
    return calls


def test_configured_channels_with_all_settings_returns_all_channel_ids():
    conn = Conn(rows=[(channels.FIREHOUSE, "C_FIRE"), (channels.REPORTS, "C_REPORTS"),
                      (channels.LOGS, "C_LOGS"), (channels.REACT_CHANNELS, "C_R1, C_R2"),
                      (responses.AUTORESPONSE_CHANNEL, "C_AUTO")])

    assert channels.configured_channels(conn) == {"C_FIRE", "C_REPORTS", "C_LOGS", "C_R1", "C_R2", "C_AUTO"}
    assert set(conn.executed[0][1][0]) == {channels.FIREHOUSE, channels.REPORTS, channels.LOGS,
                                           channels.REACT_CHANNELS, responses.AUTORESPONSE_CHANNEL}


@pytest.mark.parametrize(("how", "expected"), [
    (channels.OFF, {FIREHOUSE_ID}),
    (channels.GUARDED, {FIREHOUSE_ID, "C_GUARDED"}),
    (channels.ON, {FIREHOUSE_ID, "C_PUBLIC"}),
])
def test_target_channels_in_every_mode_includes_configured_channels(monkeypatch, how, expected):
    monkeypatch.setattr(channels, "configured_channels", lambda conn: {FIREHOUSE_ID})
    monkeypatch.setattr(channels, "guarded_channels", lambda conn: {"C_GUARDED"})
    monkeypatch.setattr(channels, "public_channels", lambda client: {"C_PUBLIC"})

    assert channels.target_channels(object(), Conn(), how) == expected


def test_missing_channels_in_off_mode_lists_absent_configured_channels(monkeypatch):
    monkeypatch.setattr(channels, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(channels, "mode", lambda conn: channels.OFF)
    monkeypatch.setattr(channels, "configured_channels", lambda conn: {FIREHOUSE_ID, "C_INSIDE"})
    monkeypatch.setattr(channels, "joined_channels", lambda client: {"C_INSIDE"})
    monkeypatch.setattr(channels, "sync_membership", lambda conn, joined_ids: (0, 0))

    assert channels.missing_channels(object()) == (channels.OFF, [FIREHOUSE_ID])


def test_join_configured_absent_public_channel_is_joined(monkeypatch):
    calls = configure(monkeypatch, {FIREHOUSE_ID, "C_INSIDE"}, inside={"C_INSIDE"})

    assert channels.join_configured(object()) == 1
    assert calls == {"joined": [FIREHOUSE_ID], "marked": []}


def test_join_configured_private_channel_calls_mark_private(monkeypatch):
    calls = configure(monkeypatch, {PRIVATE_ID}, private={PRIVATE_ID})

    assert channels.join_configured(object()) == 0
    assert calls == {"joined": [], "marked": [PRIVATE_ID]}


def test_join_configured_channel_waiting_for_invite_is_skipped(monkeypatch):
    calls = configure(monkeypatch, {PRIVATE_ID}, waiting={PRIVATE_ID}, private={PRIVATE_ID})

    assert channels.join_configured(object()) == 0
    assert calls == {"joined": [], "marked": []}


@pytest.mark.parametrize(("latest", "waiting"), [
    (("refused", channels.NEEDS_INVITE), True),
    (("refused", "is_archived"), False),
    (("joined", None), False),
    (None, False),
])
def test_waits_for_invite_true_only_when_latest_join_needs_invite(latest, waiting):
    assert channels.waits_for_invite(Conn(row=latest), PRIVATE_ID) is waiting


def test_join_sweep_runs_join_configured_before_reconcile(monkeypatch):
    order = []
    stopping = threading.Event()
    monkeypatch.setattr(loop.channels, "join_configured", lambda client: order.append("configured"))
    monkeypatch.setattr(loop.channels, "reconcile",
                        lambda client, stopping=None: order.append(("reconcile", stopping)))

    loop.join_sweep(SimpleNamespace(client=object()), stopping)

    assert order == ["configured", ("reconcile", stopping)]


def test_loop_start_app_setting_notify_starts_configured_joins(monkeypatch):
    client = object()
    started_clients, listeners = [], {}
    monkeypatch.setattr(loop, "session", lambda: session_of(Conn()))
    for module in (loop.guards, loop.channelguards, loop.memberguards, loop.automod,
                   loop.responses, loop.screening, loop.categories):
        monkeypatch.setattr(module, "refresh", lambda conn: 0)
    monkeypatch.setattr(loop.channel, "refresh_channels", lambda conn: None)
    monkeypatch.setattr(loop.purge, "requeue_interrupted", lambda conn: [])
    monkeypatch.setattr(loop.loops, "run_on_wake", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop.loops, "start_listener",
                        lambda name, names, on_notify, stopping: listeners.update(on_notify=on_notify))
    monkeypatch.setattr(loop.loops, "run_periodically", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop.loops, "run_on_timer", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop, "start_configured_joins", lambda target: started_clients.append(target))

    loop.start(SimpleNamespace(client=client), threading.Event())
    listeners["on_notify"](loop.APP_SETTING, "nemo.firehouse_channel")

    assert started_clients == [client]


def live_guards(monkeypatch, *keys):
    monkeypatch.setattr(channelguards, "_guards",
                        {(*key, channelguards.CHANNEL_WIDE): channelguards.LiveGuard(1, {}, frozenset())
                         for key in keys})
    monkeypatch.setattr(channelguards, "_loaded", True)


@pytest.mark.parametrize("kind", channelguards.KINDS)
def test_is_guarded_every_guard_kind_returns_true_for_guarded_channel(monkeypatch, kind):
    live_guards(monkeypatch, (kind, "C_GUARDED"))

    assert channelguards.is_guarded("C_GUARDED") is True
    assert channelguards.is_guarded("C_OTHER") is False


def test_is_guarded_before_first_refresh_returns_false(monkeypatch):
    monkeypatch.setattr(channelguards, "_guards", {(channelguards.READONLY, "C_GUARDED", channelguards.CHANNEL_WIDE): None})
    monkeypatch.setattr(channelguards, "_loaded", False)

    assert channelguards.is_guarded("C_GUARDED") is False


def join_channel_calls(monkeypatch, how=channels.GUARDED, inside=False):
    joined = []
    monkeypatch.setattr(loop, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(loop.channels, "mode", lambda conn: how)
    monkeypatch.setattr(loop.channels, "is_inside", lambda conn, channel_id: inside)
    monkeypatch.setattr(loop.channels, "join", lambda client, conn, channel_id, by=None, verb="joined":
                        joined.append(channel_id) or True)
    return joined


@pytest.mark.parametrize("kind", [channelguards.READONLY, channelguards.SLOWMODE,
                                  channelguards.ACCOUNT_AGE, channelguards.BOT_ALLOWLIST])
def test_join_channel_every_guard_kind_joins_channel(monkeypatch, kind):
    live_guards(monkeypatch, (kind, "C_GUARDED"))
    joined = join_channel_calls(monkeypatch)

    assert loop.join_channel(object(), "C_GUARDED") is True
    assert joined == ["C_GUARDED"]


def test_join_channel_unguarded_channel_is_skipped(monkeypatch):
    live_guards(monkeypatch)
    joined = join_channel_calls(monkeypatch)

    assert loop.join_channel(object(), "C_PLAIN") is False
    assert joined == []


def test_join_channel_already_inside_channel_is_skipped(monkeypatch):
    live_guards(monkeypatch, (channelguards.READONLY, "C_GUARDED"))
    joined = join_channel_calls(monkeypatch, inside=True)

    assert loop.join_channel(object(), "C_GUARDED") is False
    assert joined == []


class Workspace:
    def __init__(self, absent, refusing=(), stop_after=None, stopping=None):
        self.absent = list(absent)
        self.refusing = set(refusing)
        self.stop_after = stop_after
        self.stopping = stopping
        self.joins = []
        self.reads = 0

    def missing(self, client):
        self.reads += 1
        return channels.ON, [channel_id for channel_id in self.absent if channel_id not in self.joined()]

    def joined(self):
        return {channel_id for channel_id in self.joins if channel_id not in self.refusing}

    def join(self, client, conn, channel_id, by=None, verb="joined"):
        self.joins.append(channel_id)
        if self.stop_after and len(self.joins) >= self.stop_after:
            self.stopping.set()
        return channel_id not in self.refusing


def run_reconcile(monkeypatch, workspace, cap, delay=0.0, stopping=None):
    monkeypatch.setattr(channels, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(channels, "missing_channels", workspace.missing)
    monkeypatch.setattr(channels, "join", workspace.join)
    monkeypatch.setattr(channels, "join_delay_seconds", lambda: delay)
    return channels.reconcile(object(), cap=cap, stopping=stopping)


def test_reconcile_absent_channels_over_cap_joins_all_in_batches(monkeypatch):
    workspace = Workspace(["C1", "C2", "C3", "C4", "C5"])

    assert run_reconcile(monkeypatch, workspace, cap=2) == (channels.ON, 5, 0)
    assert workspace.joins == ["C1", "C2", "C3", "C4", "C5"]
    assert workspace.reads == 4


def test_reconcile_refused_channel_is_tried_once(monkeypatch):
    workspace = Workspace(["C_BAD", "C_OK"], refusing={"C_BAD"})

    assert run_reconcile(monkeypatch, workspace, cap=1) == (channels.ON, 1, 1)
    assert workspace.joins == ["C_BAD", "C_OK"]


def test_reconcile_stopping_set_stops_joins(monkeypatch):
    stopping = threading.Event()
    workspace = Workspace(["C1", "C2", "C3"], stop_after=1, stopping=stopping)

    assert run_reconcile(monkeypatch, workspace, cap=0, stopping=stopping) == (channels.ON, 1, 0)
    assert workspace.joins == ["C1"]


def test_reconcile_delay_waits_on_stopping_between_joins(monkeypatch):
    waits = []

    class Stopping:
        def is_set(self):
            return False

        def wait(self, seconds):
            waits.append(seconds)

    workspace = Workspace(["C1", "C2", "C3"])

    run_reconcile(monkeypatch, workspace, cap=2, delay=1.2, stopping=Stopping())

    assert waits == [1.2, 1.2]
