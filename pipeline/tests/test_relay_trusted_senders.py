import contextlib

import pytest

from bot.core import intake
from bot.nemo import case_channel
from bot.relay import dm

PROMETHEUS_ID = "U0AKQNSKBK4"
DM_CHANNEL_ID = "D_PROMETHEUS"


class FakeApp:
    def __init__(self):
        self.events = {}
        self.actions = {}

    def event(self, name):
        return lambda handler: self.events.setdefault(name, handler)

    def action(self, name):
        return lambda handler: self.actions.setdefault(name, handler)


class FakeConn:
    def __init__(self, results):
        self.results = results
        self.sql = None

    def execute(self, sql, args=None):
        self.sql = sql
        return self

    def fetchone(self):
        return self.results.get(self.sql)


class FakeSlack:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda **kwargs: self.calls.append((name, kwargs)) or {"ts": "9.9"}

    def methods(self):
        return [name for name, _kwargs in self.calls]


def trusted_event(**over):
    event = {"channel": DM_CHANNEL_ID, "channel_type": "im", "ts": "1.0", "user": PROMETHEUS_ID,
             "bot_id": "B_PROMETHEUS", "text": "*[Prometheus Report]* deleted a message"}
    event.update(over)
    return event


@pytest.fixture
def relay(monkeypatch):
    state = {"senders": f"{PROMETHEUS_ID},UHUMAN1", "handed_off": False, "inserted": True,
             "recorded": [], "handoffs": [], "closed": []}

    @contextlib.contextmanager
    def fake_session():
        yield FakeConn({dm.TRUSTED_SENDERS: (state["senders"],), dm.HANDED_OFF: (state["handed_off"],)})

    monkeypatch.setattr(dm, "session", fake_session)
    monkeypatch.setattr(dm.intake, "record",
                        lambda conn, event: state["recorded"].append(event["ts"]) or (41, state["inserted"]))
    monkeypatch.setattr(dm.intake, "conversation", lambda conn, channel_id, thread_ts, member=None: 7)
    monkeypatch.setattr(dm.intake, "close",
                        lambda conn, conversation_id, closed_by: state["closed"].append((conversation_id, closed_by)))

    def on_handoff(conversation_id, message_id, anonymous=True):
        state["handoffs"].append((conversation_id, message_id, anonymous))
        return 512

    app = FakeApp()
    dm.register(app, on_handoff)
    state["on_message"] = app.events["message"]
    return state


def test_dm_message_from_trusted_bot_runs_named_handoff_and_closes_conversation(relay):
    client = FakeSlack()

    assert relay["on_message"](trusted_event(), client) == 512
    assert relay["handoffs"] == [(7, 41, False)]
    assert relay["closed"] == [(7, intake.TRUSTED_SENDER)]
    assert client.calls == [("reactions_add", {"channel": DM_CHANNEL_ID, "timestamp": "1.0", "name": "white_check_mark"})]


def test_dm_message_from_trusted_human_posts_no_prompt(relay):
    client = FakeSlack()

    relay["on_message"](trusted_event(user="UHUMAN1", bot_id=None), client)

    assert relay["handoffs"] == [(7, 41, False)]
    assert "chat_postMessage" not in client.methods()


def test_dm_message_from_untrusted_bot_returns_none(relay):
    relay["senders"] = "UHUMAN1"
    client = FakeSlack()

    assert relay["on_message"](trusted_event(), client) is None
    assert relay["recorded"] == [] and relay["handoffs"] == [] and client.calls == []


@pytest.mark.parametrize(("handed_off", "inserted"), [(True, True), (False, False)])
def test_dm_trusted_message_already_handled_or_duplicate_skips_handoff(relay, handed_off, inserted):
    relay["handed_off"], relay["inserted"] = handed_off, inserted

    assert relay["on_message"](trusted_event(), FakeSlack()) is None
    assert relay["handoffs"] == [] and relay["closed"] == []


def test_dm_trusted_message_with_failing_handoff_does_not_close_conversation(relay, monkeypatch):
    app = FakeApp()
    dm.register(app, lambda conversation_id, message_id, anonymous=True: (_ for _ in ()).throw(RuntimeError("db")))

    assert app.events["message"](trusted_event(), FakeSlack()) is None
    assert relay["closed"] == []


def test_trusted_senders_parses_comma_separated_setting():
    conn = FakeConn({dm.TRUSTED_SENDERS: (" U1 , ,U2",)})

    assert dm.trusted_senders(conn) == {"U1", "U2"}
    assert dm.trusted_senders(FakeConn({})) == set()


@pytest.mark.parametrize(("closed_by", "refusal"), [
    (intake.TRUSTED_SENDER, "Not sent. Replies are disabled for trusted senders."),
    ("relay:reporter closed", "Not sent. The reporter's conversation is closed."),
])
def test_queue_reply_on_closed_conversation_posts_ephemeral_refusal(monkeypatch, closed_by, refusal):
    @contextlib.contextmanager
    def fake_session():
        yield FakeConn({case_channel.REPORT_CONVERSATION: (7, DM_CHANNEL_ID, "1.0", "2026-10-16", 30, closed_by)})

    monkeypatch.setattr(case_channel, "session", fake_session)
    client = FakeSlack()

    assert case_channel.CaseChannel(client).queue_reply("5.0", "thanks", "UMOD", at=("C_FIRE", "5.1")) is None
    assert ("chat_postEphemeral", {"channel": "C_FIRE", "user": "UMOD", "thread_ts": "5.1", "text": refusal}) \
        in client.calls
