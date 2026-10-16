from contextlib import contextmanager
from types import SimpleNamespace

from bot.nemo.surface import archive_watch

POSTED = "1700000000.000100"


def capture(monkeypatch):
    calls = []

    @contextmanager
    def session():
        yield "conn"

    def posted(conn, channel_id, message):
        calls.append(("posted", channel_id, message["ts"]))
        return True

    def edited(conn, channel_id, message):
        calls.append(("edited", channel_id, message["ts"]))
        return True

    def deleted(conn, channel_id, ts, at=None):
        calls.append(("deleted", channel_id, ts, at))
        return True

    monkeypatch.setattr(archive_watch, "session", session)
    monkeypatch.setattr(archive_watch.archive, "from_event", posted)
    monkeypatch.setattr(archive_watch.archive, "edited", edited)
    monkeypatch.setattr(archive_watch.archive, "deleted", deleted)
    return calls


def event(**fields):
    payload = {"type": "message", "channel": "C1", "channel_type": "channel"}
    payload.update(fields)
    return SimpleNamespace(payload=payload)


def test_archive_channel_message_post_records_posted(monkeypatch):
    calls = capture(monkeypatch)

    assert archive_watch.archive_channel_message(event(user="U1", text="hi", ts=POSTED))
    assert calls == [("posted", "C1", POSTED)]


def test_archive_channel_message_private_channel_post_records_posted(monkeypatch):
    calls = capture(monkeypatch)

    assert archive_watch.archive_channel_message(event(channel="G1", channel_type="group", user="U1", ts=POSTED))
    assert calls == [("posted", "G1", POSTED)]


def test_archive_channel_message_edit_records_edited(monkeypatch):
    calls = capture(monkeypatch)

    archive_watch.archive_channel_message(event(subtype="message_changed", hidden=True, ts="1700000100.000000",
                                                message={"ts": POSTED, "user": "U1", "text": "new"}))
    assert calls == [("edited", "C1", POSTED)]


def test_archive_channel_message_deletion_records_deleted(monkeypatch):
    calls = capture(monkeypatch)

    archive_watch.archive_channel_message(event(subtype="message_deleted", hidden=True, deleted_ts=POSTED,
                                                event_ts="1700000200.000000"))
    assert calls == [("deleted", "C1", POSTED, "1700000200.000000")]


def test_archive_channel_message_hidden_direct_and_channelless_events_return_none(monkeypatch):
    calls = capture(monkeypatch)

    assert archive_watch.archive_channel_message(event(subtype="message_replied", hidden=True,
                                                       message={"ts": POSTED})) is None
    assert archive_watch.archive_channel_message(event(channel="D1", channel_type="im", user="U1", ts=POSTED)) is None
    assert archive_watch.archive_channel_message(event(channel=None, user="U1", ts=POSTED)) is None
    assert calls == []


def lock_failures(monkeypatch, failures):
    attempts = []
    sleeps = []

    @contextmanager
    def session():
        yield "conn"

    def posted(conn, channel_id, message):
        attempts.append(message["ts"])
        if len(attempts) <= failures:
            raise archive_watch.LockNotAvailable("canceling statement due to lock timeout")
        return True

    monkeypatch.setattr(archive_watch, "session", session)
    monkeypatch.setattr(archive_watch.archive, "from_event", posted)
    monkeypatch.setattr(archive_watch.time, "sleep", sleeps.append)
    return attempts, sleeps


def test_archive_channel_message_retries_when_the_channel_is_locked(monkeypatch):
    attempts, sleeps = lock_failures(monkeypatch, failures=2)

    assert archive_watch.archive_channel_message(event(ts=POSTED, text="hi")) is True
    assert attempts == [POSTED] * 3
    assert sleeps == list(archive_watch.LOCK_RETRY_DELAYS_SECONDS)


def test_archive_channel_message_gives_up_after_the_last_attempt(monkeypatch):
    attempts, sleeps = lock_failures(monkeypatch, failures=10)

    assert archive_watch.archive_channel_message(event(ts=POSTED, text="hi")) is None
    assert len(attempts) == len(archive_watch.LOCK_RETRY_DELAYS_SECONDS) + 1
