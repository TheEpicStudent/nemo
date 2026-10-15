import contextlib

from bot.core import outbox
from bot.nemo import case_channel

CARD_CHANNEL_ID = "C_FIRE"
THREAD_TS = "100.000"
ECHO_TS = "200.000"


class LinkedConn:
    def execute(self, sql, args=None):
        return self

    def fetchone(self):
        return (1,)


def test_to_echo_skips_linked_author_until_two_minutes_after_send():
    assert "fd.staff_slack s" in outbox.TO_ECHO
    assert "s.staff_user_id = o.requested_by AND s.revoked_at IS NULL" in outbox.TO_ECHO
    assert "coalesce(o.sent_at, o.failed_at) < now() - interval '2 minutes'" in outbox.TO_ECHO


def test_echo_queued_posts_linked_author_row_it_was_given(monkeypatch):
    posted, echoed = [], []

    @contextlib.contextmanager
    def fake_session():
        yield LinkedConn()

    monkeypatch.setattr(case_channel, "session", fake_session)
    monkeypatch.setattr(case_channel.outbox, "to_echo", lambda conn, case_id=None: [
        (1, "hello", "signed", "ULINKED", THREAD_TS, CARD_CHANNEL_ID),
    ])
    monkeypatch.setattr(case_channel.outbox, "claim_echo", lambda conn, outbox_id: True)
    monkeypatch.setattr(case_channel.outbox, "echoed",
                        lambda conn, outbox_id, ts, echoed_as: echoed.append((outbox_id, ts, echoed_as)))
    monkeypatch.setattr(case_channel.outbox, "drop_echo", lambda conn, outbox_id: None)
    monkeypatch.setattr(case_channel.channel, "echo",
                        lambda client, thread_ts, sent_by, body, signed, channel_id=None:
                        posted.append((channel_id, thread_ts, sent_by)) or (channel_id, ECHO_TS))
    monkeypatch.setattr(case_channel.CaseChannel, "post_pending_resolutions", lambda self: None)

    assert case_channel.CaseChannel(object()).echo_queued() == 1
    assert posted == [(CARD_CHANNEL_ID, THREAD_TS, "ULINKED")]
    assert echoed == [(1, ECHO_TS, "nemo")]
