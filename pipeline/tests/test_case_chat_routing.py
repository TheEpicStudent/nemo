import contextlib

import pytest

from bot.nemo import handlers
from bot.nemo.surface import ENTRIES, reaction_watch


class App:
    def action(self, key):
        return lambda fn: fn

    def view(self, key):
        return lambda fn: fn


class Ctx:
    def __init__(self, payload):
        self.payload = payload
        self.client = None


class Conn:
    def __init__(self):
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        return None


def message_handler():
    return next(one for one in ENTRIES if one.tag == "handlers.on_message")


EVENT = {"channel": "C_FIRE", "ts": "2.0", "thread_ts": "1.0", "user": "UFD"}


@pytest.fixture
def harness(monkeypatch):
    recorded = {"replied": [], "kept": []}

    handlers.register(App(), lambda *args, **kw: recorded["replied"].append((args, kw)))

    @contextlib.contextmanager
    def one_session():
        yield Conn()

    monkeypatch.setattr(handlers, "session", one_session)
    monkeypatch.setattr(handlers, "case_channels", lambda conn=None: {"C_FIRE"})
    monkeypatch.setattr(handlers.chat, "case_of_thread", lambda conn, ts: 6)
    monkeypatch.setattr(handlers.access, "may", lambda conn, user_id, capability, case=None: (True, None))
    monkeypatch.setattr(
        handlers.chat, "store_message",
        lambda conn, case_id, event: (recorded["kept"].append((case_id, event)), (1, True))[1],
    )
    return recorded


def stub_reaches_member(monkeypatch, answer):
    monkeypatch.setattr(handlers.chat, "reaches_a_member", lambda conn, ts: answer)


def test_a_question_on_a_report_thread_goes_to_the_member(harness, monkeypatch):
    stub_reaches_member(monkeypatch, True)
    message_handler().fn(Ctx(dict(EVENT, text="?are you ok")))

    assert harness["replied"][0][0][1] == "are you ok"
    assert harness["kept"] == []


def test_a_question_with_no_member_to_reach_is_kept_as_chat(harness, monkeypatch):
    stub_reaches_member(monkeypatch, False)
    message_handler().fn(Ctx(dict(EVENT, text="?are you ok")))

    assert harness["replied"] == []
    assert harness["kept"][0][0] == 6


def test_plain_chat_never_asks_whether_a_member_can_be_reached(harness, monkeypatch):
    monkeypatch.setattr(handlers.chat, "reaches_a_member", lambda conn, ts: 1 / 0)
    message_handler().fn(Ctx(dict(EVENT, text="who is handling this")))

    assert harness["kept"][0][0] == 6


ROOT_MESSAGE = {"ts": "1.0", "user": "UMEM", "text": "that's my alt"}


def test_the_hourglassed_message_becomes_the_first_chat(monkeypatch):
    stored = []
    monkeypatch.setattr(
        reaction_watch.chat, "store_message",
        lambda conn, case_id, event: (stored.append((case_id, event)), (7, True))[1],
    )
    assert reaction_watch.store_root_message(None, 6, "C_FIRE", ROOT_MESSAGE) == 7
    assert stored[0][1]["channel"] == "C_FIRE"
    assert stored[0][1]["text"] == "that's my alt"


@pytest.mark.parametrize("message", [
    {},
    {"ts": "1.0", "user": "UMEM"},
    {"ts": "1.0", "text": "a bot said this"},
    {"user": "UMEM", "text": "no timestamp"},
])
def test_a_root_the_chat_table_would_refuse_is_left_alone(message, monkeypatch):
    monkeypatch.setattr(
        reaction_watch.chat, "store_message",
        lambda conn, case_id, event: 1 / 0,
    )
    assert reaction_watch.store_root_message(None, 6, "C_FIRE", message) is None


def test_a_root_with_only_blocks_is_still_worth_keeping():
    assert reaction_watch.is_storable({"ts": "1.0", "user": "U1", "blocks": [{}]})


class SlackCalls:
    def __init__(self):
        self.calls = []

    def chat_postEphemeral(self, **kwargs):
        self.calls.append(kwargs)


class ClientCtx(Ctx):
    def __init__(self, payload, client):
        super().__init__(payload)
        self.client = client


DELETED = {"channel": "C_FIRE", "subtype": "message_deleted", "deleted_ts": "2.0",
           "previous_message": {"user": "UFD", "thread_ts": "1.0", "ts": "2.0", "text": "?thanks"}}


@pytest.mark.parametrize(("reply", "told"), [((10, 7, "signed", "2026-10-16", "thanks"), True), (None, False)])
def test_deleting_a_delivered_reply_tells_the_moderator_it_stays(harness, monkeypatch, reply, told):
    monkeypatch.setattr(handlers.chat, "delete", lambda conn, channel_id, ts: 5)
    monkeypatch.setattr(handlers.outbox, "reply_at", lambda conn, channel_id, ts: reply)
    client = SlackCalls()

    message_handler().fn(ClientCtx(dict(DELETED), client))

    expected = [{"channel": "C_FIRE", "user": "UFD", "thread_ts": "1.0", "text": handlers.views.edits.MODERATOR_DELETE}]
    assert client.calls == (expected if told else [])


def test_editing_a_reply_queues_the_new_text(harness, monkeypatch):
    edited = []
    monkeypatch.setattr(handlers.chat, "edit", lambda conn, channel_id, message: 5)
    monkeypatch.setattr(handlers.outbox, "edit_reply",
                        lambda conn, channel_id, ts, body, by: edited.append((channel_id, ts, body, by)) or 55)
    changed = {"channel": "C_FIRE", "subtype": "message_changed",
               "message": {"ts": "2.0", "user": "UFD", "text": "?thanks, looking now", "edited": {"user": "UFD"}}}

    message_handler().fn(ClientCtx(changed, SlackCalls()))

    assert edited == [("C_FIRE", "2.0", "thanks, looking now", "UFD")]


def test_editing_chat_that_is_not_a_reply_queues_nothing(harness, monkeypatch):
    edited = []
    monkeypatch.setattr(handlers.chat, "edit", lambda conn, channel_id, message: 5)
    monkeypatch.setattr(handlers.outbox, "edit_reply", lambda *args: edited.append(args))
    changed = {"channel": "C_FIRE", "subtype": "message_changed",
               "message": {"ts": "2.0", "user": "UFD", "text": "internal chat"}}

    message_handler().fn(ClientCtx(changed, SlackCalls()))

    assert edited == []
