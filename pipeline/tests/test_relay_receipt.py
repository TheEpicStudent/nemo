import contextlib

from bot.relay import consent, dm, reply

DM_CHANNEL_ID = "D_REPORTER"
PROMPT_TS = "1.9"


def test_receipt_names_the_fire_department_and_hints_at_the_thread():
    text, blocks = reply.receipt(12, anonymous=False)

    assert text == "Your report was sent to the Fire Department."
    assert [one["text"] for one in blocks[1]["elements"]] == [reply.THREAD_HINT]


def test_receipt_lists_anonymous_and_delay_before_the_hint():
    _text, blocks = reply.receipt(12, anonymous=True, delayed=True)

    assert [one["text"] for one in blocks[1]["elements"]] == \
        [reply.ANONYMOUS, reply.DELIVERY_DELAYED, reply.THREAD_HINT]


class FakeConn:
    def __init__(self, results):
        self.results = results
        self.sql = None

    def execute(self, sql, args=None):
        self.sql = sql
        return self

    def fetchone(self):
        return self.results.get(self.sql)

    def fetchall(self):
        return self.results.get(self.sql, [])


class FakeSlack:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda **kwargs: self.calls.append((name, kwargs)) or {"ok": True}


class FakeApp:
    def __init__(self):
        self.actions = {}

    def event(self, name):
        return lambda handler: handler

    def action(self, name):
        return lambda handler: self.actions.setdefault(name, handler)


def test_send_ticks_every_message_in_the_report(monkeypatch):
    results = {
        dm.CONVERSATION_BY_MESSAGE: (7,),
        dm.CONVERSATION_STATE: (False, PROMPT_TS, None),
        dm.LATEST_INBOUND_MESSAGE: (42,),
        dm.SUBMITTED_MESSAGES: [(DM_CHANNEL_ID, "1.0"), (DM_CHANNEL_ID, "1.2")],
    }

    @contextlib.contextmanager
    def fake_session():
        yield FakeConn(results)

    monkeypatch.setattr(dm, "session", fake_session)
    monkeypatch.setattr(dm, "nemo_delayed", lambda conn: False)
    app = FakeApp()
    dm.register(app, lambda conversation_id, message_id, anonymous=True: 512)
    client = FakeSlack()

    app.actions[consent.CONFIRM](lambda: None, {"channel": {"id": DM_CHANNEL_ID}, "message": {"ts": PROMPT_TS}}, client)

    names = [name for name, _kwargs in client.calls]
    assert names == ["chat_update", "reactions_add", "reactions_add"]
    assert client.calls[0][1]["text"] == reply.SUBMITTED
    assert [kwargs["timestamp"] for name, kwargs in client.calls[1:]] == ["1.0", "1.2"]
    assert all(kwargs["name"] == reply.RECEIVED_REACTION for _name, kwargs in client.calls[1:])


def test_submitted_messages_query_takes_live_inbound_messages():
    assert "direction = 'inbound' AND deleted_at IS NULL" in dm.SUBMITTED_MESSAGES
