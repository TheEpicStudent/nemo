import contextlib

from bot.relay import consent, dm, reply

DM_CHANNEL_ID = "D_REPORTER"
PROMPT_TS = "1.9"


def test_receipt_names_the_fire_department_and_hints_at_the_thread():
    text, blocks = reply.receipt(12, anonymous=False)

    assert text == "Your report was sent to the Fire Department."
    assert blocks[1]["elements"] == [{"type": "mrkdwn", "text": reply.THREAD_HINT}]


def test_receipt_mentions_the_reporter_first():
    text, blocks = reply.receipt(12, anonymous=False, reporter_id="UREPORTER")

    assert text == "<@UREPORTER>: Your report was sent to the Fire Department."
    assert blocks[0]["text"]["text"] == text


def test_receipt_lists_anonymous_and_delay_before_the_hint():
    _text, blocks = reply.receipt(12, anonymous=True, delayed=True)

    assert blocks[1]["elements"] == [{"type": "mrkdwn", "text":
        f"{reply.ANONYMOUS} - {reply.DELIVERY_DELAYED} - {reply.THREAD_HINT}"}]


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


class RecordingConn(FakeConn):
    def __init__(self, results, executed):
        super().__init__(results)
        self.executed = executed

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return super().execute(sql, args)


def send_setup(monkeypatch, claimed=True, on_submit=None):
    executed = []
    results = {
        dm.CLAIM_PROMPT: (7,) if claimed else None,
        dm.CONVERSATION_STATE: (False, None, None),
        dm.LATEST_INBOUND_MESSAGE: (42,),
        dm.SUBMITTED_MESSAGES: [(DM_CHANNEL_ID, "1.0"), (DM_CHANNEL_ID, "1.2")],
    }

    @contextlib.contextmanager
    def fake_session():
        yield RecordingConn(results, executed)

    monkeypatch.setattr(dm, "session", fake_session)
    monkeypatch.setattr(dm, "nemo_delayed", lambda conn: False)
    app = FakeApp()
    dm.register(app, on_submit or (lambda conversation_id, message_id, anonymous=True: 512))
    return app, executed


def press(app, action, client):
    app.actions[action](lambda: None, {"channel": {"id": DM_CHANNEL_ID}, "message": {"ts": PROMPT_TS},
                                       "user": {"id": "UREPORTER"}}, client)


def test_send_shows_sending_then_the_receipt_and_ticks_every_message(monkeypatch):
    app, _executed = send_setup(monkeypatch)
    client = FakeSlack()

    press(app, consent.CONFIRM, client)

    assert [name for name, _kwargs in client.calls] == ["chat_update", "chat_update", "reactions_add", "reactions_add"]
    assert client.calls[0][1]["text"] == reply.SENDING
    assert client.calls[1][1]["text"] == reply.SUBMITTED
    assert [kwargs["timestamp"] for _name, kwargs in client.calls[2:]] == ["1.0", "1.2"]


def test_send_pressed_again_while_sending_does_nothing(monkeypatch):
    submitted = []
    app, _executed = send_setup(monkeypatch, claimed=False,
                                on_submit=lambda conversation_id, message_id, anonymous=True: submitted.append(1))
    client = FakeSlack()

    press(app, consent.CONFIRM, client)

    assert client.calls == [] and submitted == []


def test_send_failure_restores_the_prompt_for_a_later_message(monkeypatch):
    def failing_submit(conversation_id, message_id, anonymous=True):
        raise RuntimeError("database unavailable")

    app, executed = send_setup(monkeypatch, on_submit=failing_submit)
    client = FakeSlack()

    press(app, consent.CONFIRM, client)

    assert client.calls[-1][1]["text"] == reply.SUBMIT_FAILED
    assert (dm.SET_PROMPT_SUBTYPE, (consent.SUBTYPE, DM_CHANNEL_ID, PROMPT_TS)) in executed


def test_cancel_after_send_was_claimed_does_nothing(monkeypatch):
    purged = []
    app, _executed = send_setup(monkeypatch, claimed=False)
    monkeypatch.setattr(dm.blobs, "purge_conversation", lambda conn, conversation_id, by: purged.append(1) or (0, 0))
    client = FakeSlack()

    press(app, consent.CANCEL, client)

    assert client.calls == [] and purged == []


def test_claim_prompt_only_takes_an_unanswered_prompt():
    assert "AND subtype = %s" in dm.CLAIM_PROMPT and "RETURNING conversation_id" in dm.CLAIM_PROMPT


def test_submitted_messages_query_takes_live_inbound_messages():
    assert "direction = 'inbound' AND deleted_at IS NULL" in dm.SUBMITTED_MESSAGES
