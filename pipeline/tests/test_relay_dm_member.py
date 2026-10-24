import contextlib

from bot.relay import dm


class FakeConn:
    def execute(self, sql, args=None):
        return self

    def fetchone(self):
        return (False, None, None)

    def fetchall(self):
        return []


class FakeSlack:
    def __getattr__(self, name):
        return lambda **kwargs: {"ok": True, "ts": "9.9"}


class FakeApp:
    def __init__(self):
        self.events = {}

    def event(self, name):
        return lambda handler: self.events.setdefault(name, handler)

    def action(self, name):
        return lambda handler: handler


def message_event(**over):
    event = {"channel_type": "im", "channel": "D1", "ts": "1.5", "thread_ts": "1.0",
             "user": "UREPORTER", "text": "a temp report"}
    event.update(over)
    return event


def setup(monkeypatch, trusted=()):
    calls = {"conversation": []}

    @contextlib.contextmanager
    def fake_session():
        yield FakeConn()

    def conversation(conn, channel_id, thread_ts, member_user_id=None):
        calls["conversation"].append((channel_id, thread_ts, member_user_id))
        return 7

    monkeypatch.setattr(dm, "session", fake_session)
    monkeypatch.setattr(dm, "trusted_senders", lambda conn: set(trusted))
    monkeypatch.setattr(dm.intake, "record", lambda conn, event, direction="inbound": (42, True))
    monkeypatch.setattr(dm.intake, "rename_anonymous_files", lambda conn, conversation_id: [])
    monkeypatch.setattr(dm.intake, "conversation", conversation)
    monkeypatch.setattr(dm, "preview", lambda conn, conversation_id, saved_choice=None: [])
    return FakeApp(), calls


def test_a_dm_report_records_the_reporter_on_the_conversation(monkeypatch):
    app, calls = setup(monkeypatch)
    dm.register(app, on_submit=lambda conversation_id, message_id, anonymous=True: 512)

    app.events["message"](message_event(), FakeSlack())

    assert calls["conversation"] == [("D1", "1.0", "UREPORTER")]


def test_a_trusted_dm_report_records_the_sender_on_the_conversation(monkeypatch):
    app, calls = setup(monkeypatch, trusted={"U0PROM"})
    submitted = []
    dm.register(app, on_submit=lambda *args: submitted.append(args) or 512)

    app.events["message"](message_event(user="U0PROM"), FakeSlack())

    assert calls["conversation"][-1] == ("D1", "1.0", "U0PROM")
    assert submitted == [(7, 42, False)]
