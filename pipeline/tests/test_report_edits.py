import contextlib
from types import SimpleNamespace

from bot.core import formatting, outbox
from bot.nemo import channel
from bot.nemo.views import edits
from bot.relay import dm, messages, reply

CARD_TS = "1700000400.000900"


def texts(notice):
    return [element["elements"][0]["text"] for element in notice["blocks"][1]["elements"]]


def test_edit_notice_shows_from_and_to_with_a_link():
    notice = edits.edit_notice("https://hackclub.slack.com/archives/C1/p1", "old text", "new text")

    assert notice["text"] == "Reporter edited a message"
    assert notice["blocks"][0]["elements"][0]["text"] == \
        "Reporter edited a message · <https://hackclub.slack.com/archives/C1/p1|message>"
    assert texts(notice) == ["From", "old text", "To", "new text"]


def test_edit_notice_names_empty_text():
    assert texts(edits.edit_notice(None, "", "added words"))[1] == edits.NO_TEXT


class EditConn:
    def __init__(self, rows):
        self.rows = rows
        self.shown = []

    def execute(self, sql, args=None):
        if sql == channel.SHOWN:
            self.shown.append(args)
        return self

    def fetchall(self):
        return self.rows


class Slack:
    def __init__(self, failing=()):
        self.failing = failing
        self.calls = []

    def __getattr__(self, name):
        def call(**kwargs):
            if name in self.failing:
                raise RuntimeError("ratelimited")
            self.calls.append((name, kwargs))
            return {"ts": "9.9"}
        return call


def test_post_edit_notices_posts_under_the_card_and_records_what_it_showed(monkeypatch):
    monkeypatch.setattr(channel, "channel_or_firehouse", lambda stored, channel_id, conn: stored)
    conn = EditConn([(7, "1700000401.000100", "old", "new", CARD_TS, "C_FIRE")])
    client = Slack()

    assert channel.post_edit_notices(client, conn, 3) == 1
    name, posted = client.calls[0]
    assert (name, posted["channel"], posted["thread_ts"]) == ("chat_postMessage", "C_FIRE", CARD_TS)
    assert texts(posted)[1::2] == ["old", "new"]
    assert conn.shown == [("new", 7)]


def test_edits_waiting_query_takes_mirrored_inbound_changes_only():
    sql = channel.EDITS_WAITING
    assert "m.direction = 'inbound' AND m.deleted_at IS NULL" in sql
    assert "m.mirrored_ts IS NOT NULL AND r.forwarded_ts IS NOT NULL" in sql
    assert "IS DISTINCT FROM coalesce(m.shown_body, first_revision.body, '')" in sql


class OutboxConn:
    def __init__(self, reply_row, unsent_claimed=False):
        self.reply_row = reply_row
        self.unsent_claimed = unsent_claimed
        self.queued = []
        self.sql = None

    def execute(self, sql, args=None):
        self.sql, self.args = sql, args
        if sql == outbox.QUEUE:
            self.queued.append(args)
        return self

    def fetchone(self):
        if self.sql == outbox.REPLY_AT:
            return self.reply_row
        if self.sql == outbox.EDIT_UNSENT:
            return None if self.unsent_claimed else (self.args[1],)
        if self.sql == outbox.QUEUE:
            return (55,)
        return (1,)


def test_edit_reply_with_unchanged_text_does_nothing():
    conn = OutboxConn((10, 7, "signed", "2026-10-16", "same words"))

    assert outbox.edit_reply(conn, "C1", "1.1", "same words", "UMOD") is None
    assert conn.queued == []


def test_edit_reply_before_sending_replaces_the_queued_text():
    conn = OutboxConn((10, 7, "signed", None, "draft"))

    assert outbox.edit_reply(conn, "C1", "1.1", "final", "UMOD") == 10
    assert conn.queued == []


def test_edit_reply_after_sending_queues_an_edit_with_the_original_mode():
    conn = OutboxConn((10, 7, "body", "2026-10-16", "old words"))

    assert outbox.edit_reply(conn, "C1", "1.1", "new words", "UMOD") == 55
    conversation_id, kind, body, mode, requested_by, _files, asked_in, asked_at, edits_outbox_id = conn.queued[0]
    assert (conversation_id, kind, body, mode, requested_by, asked_in, asked_at, edits_outbox_id) == \
        (7, "edit", "new words", "body", "UMOD", "C1", "1.1", 10)


def test_edit_reply_for_a_message_that_is_not_a_reply_does_nothing():
    assert outbox.edit_reply(OutboxConn(None), "C1", "1.1", "words", "UMOD") is None


class DeliverConn:
    def __init__(self, original):
        self.original = original
        self.sql = None

    def execute(self, sql, args=None):
        self.sql = sql
        return self

    def fetchone(self):
        return self.original if self.sql == messages.EDITED_MESSAGE else None


def edit_queued(body):
    return SimpleNamespace(id=56, kind="edit", body=body, edits_outbox_id=10, closed_at=None, channel_id="D1",
                           thread_ts="1.0", mode="body", requested_by="UMOD", last_try=False)


def deliver(monkeypatch, original, body):
    done = {"sent": [], "errors": [], "edited": [], "recorded": []}
    monkeypatch.setattr(messages.outbox, "sent", lambda conn, outbox_id, message_id: done["sent"].append(message_id))
    monkeypatch.setattr(messages.outbox, "mark_error",
                        lambda conn, outbox_id, error, give_up: done["errors"].append(str(error)))
    monkeypatch.setattr(messages.intake, "edit", lambda conn, channel_id, message: done["edited"].append(message))
    monkeypatch.setattr(messages.intake, "record",
                        lambda conn, event, direction, sent_by: done["recorded"].append(event) or (77, True))
    relay = messages.MessageRelay()
    relay.client = Slack()
    result = relay.deliver_message(DeliverConn(original), edit_queued(body))
    return result, relay.client.calls, done


def test_deliver_edit_updates_a_short_reply_in_place(monkeypatch):
    result, calls, done = deliver(monkeypatch, (40, "D1", "1.5", "old words"), "new words")

    assert result is True
    assert calls == [("chat_update", {"channel": "D1", "ts": "1.5", "text": "new words"})]
    assert done["edited"] == [{"ts": "1.5", "text": "new words"}]
    assert done["sent"] == [40]


def test_deliver_edit_of_a_long_reply_posts_the_new_text_as_edited(monkeypatch):
    long_body = "word " * (formatting.MEMBER_PART_LIMIT // 4)
    result, calls, done = deliver(monkeypatch, (40, "D1", "1.5", "old words"), long_body)

    assert result is True
    assert [name for name, _kwargs in calls] == ["chat_postMessage", "chat_postMessage"]
    assert calls[0][1]["text"].startswith(reply.EDITED_PREFIX)
    assert done["sent"] == [77]


def test_deliver_edit_without_the_sent_original_gives_up(monkeypatch):
    result, calls, done = deliver(monkeypatch, None, "new words")

    assert result is False
    assert done["errors"] == ["the edited reply was never sent"] and calls == []


class StateConn:
    def __init__(self, reported):
        self.reported = reported

    def execute(self, sql, args=None):
        self.sql = sql
        return self

    def fetchone(self):
        return (1,) if self.sql == dm.REPORTED_INBOUND and self.reported else None


class FakeApp:
    def __init__(self):
        self.events = {}

    def event(self, name):
        return lambda handler: self.events.setdefault(name, handler)

    def action(self, name):
        return lambda handler: handler


def delete_event():
    return {"channel": "D1", "channel_type": "im", "subtype": "message_deleted", "deleted_ts": "1.5",
            "previous_message": {"user": "UREPORTER1", "thread_ts": "1.0", "ts": "1.5"}}


def run_delete(monkeypatch, reported):
    @contextlib.contextmanager
    def fake_session():
        yield StateConn(reported)

    monkeypatch.setattr(dm, "session", fake_session)
    monkeypatch.setattr(dm.intake, "delete", lambda conn, channel_id, ts: 40)
    app = FakeApp()
    dm.register(app, None)
    client = Slack()
    app.events["message"](delete_event(), client)
    return client.calls


def test_reporter_delete_after_send_is_told_it_stays(monkeypatch):
    assert run_delete(monkeypatch, reported=True) == [
        ("chat_postEphemeral", {"channel": "D1", "user": "UREPORTER1", "thread_ts": "1.0", "text": reply.REPORTER_DELETE}),
    ]


def test_reporter_delete_before_send_says_nothing(monkeypatch):
    assert run_delete(monkeypatch, reported=False) == []
