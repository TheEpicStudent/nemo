import contextlib

import pytest

from bot.nemo import case_channel

FIREHOUSE_ID = "C_FIRE"
OLD_CHANNEL_ID = "G_OLD"
THREAD_TS = "100.000"
MIRROR_TS = "200.000"


class Conn:
    def execute(self, sql, args=None):
        return self

    def fetchone(self):
        return None


@pytest.fixture
def mirror_calls(monkeypatch):
    calls = {"posted": [], "mirrored": []}

    @contextlib.contextmanager
    def fake_session():
        yield Conn()

    monkeypatch.setattr(case_channel, "session", fake_session)
    monkeypatch.setattr(case_channel.outbox, "claim_mirror", lambda conn, outbox_id: True)
    monkeypatch.setattr(
        case_channel.outbox, "mark_mirrored",
        lambda conn, outbox_id, ts, mirrored_as: calls["mirrored"].append((outbox_id, ts, mirrored_as)),
    )
    monkeypatch.setattr(case_channel.outbox, "release_mirror", lambda conn, outbox_id: None)
    monkeypatch.setattr(case_channel.channel, "firehouse_channel", lambda conn=None: FIREHOUSE_ID)
    monkeypatch.setattr(
        case_channel.channel, "post_outbox_reply",
        lambda client, thread_ts, sent_by, body, signed, channel_id=None:
            calls["posted"].append((channel_id, thread_ts)) or (channel_id, MIRROR_TS),
    )
    monkeypatch.setattr(case_channel.CaseChannel, "post_pending_resolutions", lambda self: None)
    return calls


def queue_mirrors(monkeypatch, rows):
    monkeypatch.setattr(case_channel.outbox, "to_mirror", lambda conn, case_id=None: rows)


def test_mirror_outbox_replies_posts_in_report_card_channel(monkeypatch, mirror_calls):
    queue_mirrors(monkeypatch, [(1, "hello", "signed", "USTAFF", THREAD_TS, OLD_CHANNEL_ID)])

    assert case_channel.CaseChannel(object()).mirror_outbox_replies() == 1
    assert mirror_calls["posted"] == [(OLD_CHANNEL_ID, THREAD_TS)]
    assert mirror_calls["mirrored"] == [(1, MIRROR_TS, "nemo")]


def test_mirror_outbox_replies_without_card_channel_uses_firehouse(monkeypatch, mirror_calls):
    queue_mirrors(monkeypatch, [(1, "hello", "signed", "USTAFF", THREAD_TS, None)])

    case_channel.CaseChannel(object()).mirror_outbox_replies()

    assert mirror_calls["posted"] == [(FIREHOUSE_ID, THREAD_TS)]


def test_mirror_outbox_replies_posts_each_row_in_its_own_channel(monkeypatch, mirror_calls):
    queue_mirrors(monkeypatch, [
        (1, "first", "signed", "USTAFF", THREAD_TS, OLD_CHANNEL_ID),
        (2, "second", "body", "USTAFF", "300.000", FIREHOUSE_ID),
    ])

    assert case_channel.CaseChannel(object()).mirror_outbox_replies() == 2
    assert mirror_calls["posted"] == [(OLD_CHANNEL_ID, THREAD_TS), (FIREHOUSE_ID, "300.000")]
