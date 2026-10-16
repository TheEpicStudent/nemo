import contextlib

from bot.relay import dm, reply


class FakeApp:
    def __init__(self):
        self.events = {}

    def event(self, name):
        return lambda handler: self.events.setdefault(name, handler)

    def action(self, name):
        return lambda handler: handler


class FakeSlack:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda **kwargs: self.calls.append((name, kwargs)) or {"ts": "9.9"}


def message_handler(monkeypatch, session_factory):
    monkeypatch.setattr(dm, "session", session_factory)
    app = FakeApp()
    dm.register(app, None)
    return app.events["message"]


@contextlib.contextmanager
def failing_session():
    raise RuntimeError("database unavailable")
    yield


def dm_event(**over):
    event = {"channel": "D1", "channel_type": "im", "ts": "1.5", "user": "UREPORTER1", "text": "help"}
    event.update(over)
    return event


def test_message_store_failure_tells_the_reporter_to_resend(monkeypatch):
    client = FakeSlack()

    message_handler(monkeypatch, failing_session)(dm_event(), client)

    assert client.calls == [("chat_postEphemeral", {"channel": "D1", "user": "UREPORTER1", "thread_ts": None,
                                                    "text": reply.RECEIVE_FAILED})]


def test_message_store_failure_in_a_thread_answers_in_that_thread(monkeypatch):
    client = FakeSlack()

    message_handler(monkeypatch, failing_session)(dm_event(thread_ts="1.0"), client)

    assert client.calls[0][1]["thread_ts"] == "1.0"


def test_message_store_failure_without_a_user_says_nothing(monkeypatch):
    client = FakeSlack()

    message_handler(monkeypatch, failing_session)(dm_event(user=None), client)

    assert client.calls == []
