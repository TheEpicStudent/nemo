import contextlib

import pytest

from bot.nemo import case_channel

FIREHOUSE_ID = "C_FIRE"
OLD_CHANNEL_ID = "G_OLD"
THREAD_TS = "100.000"
ECHO_TS = "200.000"


class Conn:
    def execute(self, sql, args=None):
        return self

    def fetchone(self):
        return None


@pytest.fixture
def echo_calls(monkeypatch):
    calls = {"posted": [], "echoed": []}

    @contextlib.contextmanager
    def fake_session():
        yield Conn()

    monkeypatch.setattr(case_channel, "session", fake_session)
    monkeypatch.setattr(case_channel.outbox, "claim_echo", lambda conn, outbox_id: True)
    monkeypatch.setattr(
        case_channel.outbox, "echoed",
        lambda conn, outbox_id, ts, echoed_as: calls["echoed"].append((outbox_id, ts, echoed_as)),
    )
    monkeypatch.setattr(case_channel.outbox, "drop_echo", lambda conn, outbox_id: None)
    monkeypatch.setattr(case_channel.channel, "internal_log_channel", lambda conn=None: FIREHOUSE_ID)
    monkeypatch.setattr(
        case_channel.channel, "echo",
        lambda client, thread_ts, sent_by, body, signed, channel_id=None:
            calls["posted"].append((channel_id, thread_ts)) or (channel_id, ECHO_TS),
    )
    monkeypatch.setattr(case_channel.CaseChannel, "post_pending_resolutions", lambda self: None)
    return calls


def queue_echoes(monkeypatch, rows):
    monkeypatch.setattr(case_channel.outbox, "to_echo", lambda conn, case_id=None: rows)


def test_echo_queued_posts_in_report_card_channel(monkeypatch, echo_calls):
    queue_echoes(monkeypatch, [(1, "hello", "signed", "USTAFF", THREAD_TS, OLD_CHANNEL_ID)])

    assert case_channel.CaseChannel(object()).echo_queued() == 1
    assert echo_calls["posted"] == [(OLD_CHANNEL_ID, THREAD_TS)]
    assert echo_calls["echoed"] == [(1, ECHO_TS, "nemo")]


def test_echo_queued_without_card_channel_uses_firehouse(monkeypatch, echo_calls):
    queue_echoes(monkeypatch, [(1, "hello", "signed", "USTAFF", THREAD_TS, None)])

    case_channel.CaseChannel(object()).echo_queued()

    assert echo_calls["posted"] == [(FIREHOUSE_ID, THREAD_TS)]


def test_echo_queued_keeps_each_row_in_its_own_room(monkeypatch, echo_calls):
    queue_echoes(monkeypatch, [
        (1, "first", "signed", "USTAFF", THREAD_TS, OLD_CHANNEL_ID),
        (2, "second", "body", "USTAFF", "300.000", FIREHOUSE_ID),
    ])

    assert case_channel.CaseChannel(object()).echo_queued() == 2
    assert echo_calls["posted"] == [(OLD_CHANNEL_ID, THREAD_TS), (FIREHOUSE_ID, "300.000")]
