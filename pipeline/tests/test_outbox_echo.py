import contextlib

from bot.core import outbox
from bot.nemo import case_channel

CARD_CHANNEL_ID = "C_FIRE"
THREAD_TS = "100.000"
MIRROR_TS = "200.000"


class LinkedConn:
    def execute(self, sql, args=None):
        return self

    def fetchone(self):
        return (1,)


def test_to_mirror_linked_author_within_two_minutes_is_skipped():
    assert "fd.staff_slack s" in outbox.TO_MIRROR
    assert "s.staff_user_id = o.requested_by AND s.revoked_at IS NULL" in outbox.TO_MIRROR
    assert "coalesce(o.sent_at, o.failed_at) < now() - interval '2 minutes'" in outbox.TO_MIRROR


def test_mirror_outbox_replies_linked_author_row_posts_and_marks_mirrored(monkeypatch):
    posted, mirrored = [], []

    @contextlib.contextmanager
    def fake_session():
        yield LinkedConn()

    monkeypatch.setattr(case_channel, "session", fake_session)
    monkeypatch.setattr(case_channel.outbox, "to_mirror", lambda conn, case_id=None: [
        (1, "hello", "signed", "ULINKED", THREAD_TS, CARD_CHANNEL_ID),
    ])
    monkeypatch.setattr(case_channel.outbox, "claim_mirror", lambda conn, outbox_id: True)
    monkeypatch.setattr(case_channel.outbox, "mark_mirrored",
                        lambda conn, outbox_id, ts, how: mirrored.append((outbox_id, ts, how)))
    monkeypatch.setattr(case_channel.outbox, "release_mirror", lambda conn, outbox_id: None)
    monkeypatch.setattr(case_channel.channel, "post_outbox_reply",
                        lambda client, thread_ts, sent_by, body, signed, channel_id=None:
                        posted.append((channel_id, thread_ts, sent_by)) or (channel_id, MIRROR_TS))
    monkeypatch.setattr(case_channel.CaseChannel, "post_pending_resolutions", lambda self: None)

    assert case_channel.CaseChannel(object()).mirror_outbox_replies() == 1
    assert posted == [(CARD_CHANNEL_ID, THREAD_TS, "ULINKED")]
    assert mirrored == [(1, MIRROR_TS, "nemo")]
