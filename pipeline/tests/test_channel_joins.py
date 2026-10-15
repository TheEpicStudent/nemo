import contextlib
import threading
from types import SimpleNamespace

import pytest

from bot.nemo import channels, loop, responses

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
    monkeypatch.setattr(channels, "inside", lambda conn, channel_id: channel_id in inside)
    monkeypatch.setattr(channels, "waits_for_invite", lambda conn, channel_id: channel_id in waiting)
    monkeypatch.setattr(channels, "joinable", lambda conn, channel_id: channel_id not in private)
    monkeypatch.setattr(channels, "join", lambda client, conn, channel_id, by=None, verb="joined":
                        calls["joined"].append(channel_id) or True)
    monkeypatch.setattr(channels, "mark_private", lambda client, conn, channel_id, by:
                        calls["marked"].append(channel_id) or False)
    return calls


def test_configured_channels_reads_every_channel_setting():
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
def test_target_channels_include_configured_channels_in_every_mode(monkeypatch, how, expected):
    monkeypatch.setattr(channels, "configured_channels", lambda conn: {FIREHOUSE_ID})
    monkeypatch.setattr(channels, "guarded_channels", lambda conn: {"C_GUARDED"})
    monkeypatch.setattr(channels, "public_channels", lambda client: {"C_PUBLIC"})

    assert channels.target_channels(object(), Conn(), how) == expected


def test_missing_in_off_mode_lists_absent_configured_channels(monkeypatch):
    monkeypatch.setattr(channels, "session", lambda: session_of(Conn()))
    monkeypatch.setattr(channels, "mode", lambda conn: channels.OFF)
    monkeypatch.setattr(channels, "configured_channels", lambda conn: {FIREHOUSE_ID, "C_INSIDE"})
    monkeypatch.setattr(channels, "joined_channels", lambda client: {"C_INSIDE"})
    monkeypatch.setattr(channels, "sync_membership", lambda conn, joined_ids: (0, 0))

    assert channels.missing(object()) == (channels.OFF, [FIREHOUSE_ID])


def test_join_configured_joins_absent_public_channel(monkeypatch):
    calls = configure(monkeypatch, {FIREHOUSE_ID, "C_INSIDE"}, inside={"C_INSIDE"})

    assert channels.join_configured(object()) == 1
    assert calls == {"joined": [FIREHOUSE_ID], "marked": []}


def test_join_configured_marks_private_channel_as_needing_invite(monkeypatch):
    calls = configure(monkeypatch, {PRIVATE_ID}, private={PRIVATE_ID})

    assert channels.join_configured(object()) == 0
    assert calls == {"joined": [], "marked": [PRIVATE_ID]}


def test_join_configured_skips_channel_already_waiting_for_invite(monkeypatch):
    calls = configure(monkeypatch, {PRIVATE_ID}, waiting={PRIVATE_ID}, private={PRIVATE_ID})

    assert channels.join_configured(object()) == 0
    assert calls == {"joined": [], "marked": []}


@pytest.mark.parametrize(("latest", "waiting"), [
    (("refused", channels.NEEDS_INVITE), True),
    (("refused", "is_archived"), False),
    (("joined", None), False),
    (None, False),
])
def test_waits_for_invite_reads_latest_join(latest, waiting):
    assert channels.waits_for_invite(Conn(row=latest), PRIVATE_ID) is waiting


def test_join_sweep_joins_configured_channels_before_reconcile(monkeypatch):
    order = []
    monkeypatch.setattr(loop.channels, "join_configured", lambda client: order.append("configured"))
    monkeypatch.setattr(loop.channels, "reconcile", lambda client: order.append("reconcile"))

    loop.join_sweep(SimpleNamespace(client=object()))

    assert order == ["configured", "reconcile"]


def test_app_setting_notify_starts_configured_joins(monkeypatch):
    client = object()
    started, watched = [], {}
    monkeypatch.setattr(loop, "session", lambda: session_of(Conn()))
    for module in (loop.guards, loop.channelguards, loop.memberguards, loop.automod,
                   loop.responses, loop.screening):
        monkeypatch.setattr(module, "refresh", lambda conn: 0)
    monkeypatch.setattr(loop.channel, "refresh_channels", lambda conn: None)
    monkeypatch.setattr(loop.purge, "requeue_stranded", lambda conn: [])
    monkeypatch.setattr(loop.loops, "draining", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop.loops, "watching",
                        lambda name, names, on_notify, stopping: watched.update(on_notify=on_notify))
    monkeypatch.setattr(loop.loops, "sweeping", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, "start_configured_joins", lambda one: started.append(one))

    loop.start(SimpleNamespace(client=client), threading.Event())
    watched["on_notify"](loop.APP_SETTING, "nemo.firehouse_channel")

    assert started == [client]
