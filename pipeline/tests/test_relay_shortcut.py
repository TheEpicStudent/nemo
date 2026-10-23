import contextlib

import pytest

from bot.core import case
from bot.relay import consent, shortcut
from bot.relay.reply import SENDING, SUBMIT_FAILED

REPORTER = "UREPORTER"
AUTHOR = "UAUTHOR"
ORIGIN = "C0CONSTRUCT"
MESSAGE_TS = "1792379645.000100"
DM_CHANNEL = "D0REPORTER"
ROOT_TS = "1792379700.000200"


class FakeApp:
    def __init__(self):
        self.shortcuts = {}

    def shortcut(self, callback_id):
        return lambda handler: self.shortcuts.setdefault(callback_id, handler)


class FakeSlack:
    def __init__(self, users=None, fail=None):
        self.users = users or {}
        self.fail = fail
        self.calls = []

    def conversations_open(self, **kwargs):
        self.calls.append(("conversations_open", kwargs))
        if self.fail == "open":
            raise RuntimeError("cannot_dm_bot")
        return {"channel": {"id": DM_CHANNEL}}

    def chat_postMessage(self, **kwargs):
        self.calls.append(("chat_postMessage", kwargs))
        return {"ts": ROOT_TS}

    def chat_update(self, **kwargs):
        self.calls.append(("chat_update", kwargs))
        return {}

    def users_info(self, user):
        self.calls.append(("users_info", {"user": user}))
        if user not in self.users:
            raise RuntimeError("user_not_found")
        return {"user": self.users[user]}

    def updates(self):
        return [kwargs for name, kwargs in self.calls if name == "chat_update"]


class Responder:
    def __init__(self):
        self.said = []

    def __call__(self, **kwargs):
        self.said.append(kwargs["text"])


def payload(**message):
    base = {"ts": MESSAGE_TS, "user": AUTHOR, "text": "mmm"}
    base.update(message)
    return {"user": {"id": REPORTER}, "channel": {"id": ORIGIN, "name": "construction"}, "message": base,
            "action_ts": "1792379699.000100"}


@pytest.fixture
def relay(monkeypatch):
    state = {"recorded": [], "handoffs": [], "conversations": [], "fail_handoff": False, "delayed": False}

    @contextlib.contextmanager
    def fake_session():
        yield object()

    def record(conn, event, direction="inbound", sent_by=None):
        state["recorded"].append((direction, event))
        return (41 if direction == "inbound" else 40), True

    def on_submit(conversation_id, message_id, anonymous=True, subject_user_id=None, entry_point=case.DM):
        if state["fail_handoff"]:
            raise RuntimeError("database down")
        state["handoffs"].append((conversation_id, message_id, anonymous, subject_user_id, entry_point))
        return 512

    monkeypatch.setattr(shortcut, "session", fake_session)
    monkeypatch.setattr(shortcut, "nemo_delayed", lambda conn: state["delayed"])
    monkeypatch.setattr(shortcut.intake, "record", record)
    monkeypatch.setattr(shortcut.intake, "conversation",
                        lambda conn, channel_id, thread_ts, member=None:
                        state["conversations"].append((channel_id, thread_ts, member)) or 7)
    app = FakeApp()
    shortcut.register(app, on_submit)
    state["app"] = app
    return state


def run(relay, callback_id, body, slack=None):
    slack = slack or FakeSlack()
    responder = Responder()
    acked = []
    relay["app"].shortcuts[callback_id](lambda: acked.append(True), body, slack, responder)
    assert acked == [True]
    return slack, responder


def test_register_adds_both_report_shortcuts(relay):
    assert set(relay["app"].shortcuts) == {shortcut.REPORT_ANONYMOUS, shortcut.REPORT_WITH_NAME}


@pytest.mark.parametrize(("callback_id", "anonymous"), [
    (shortcut.REPORT_ANONYMOUS, True),
    (shortcut.REPORT_WITH_NAME, False),
])
def test_report_hands_over_with_the_choice_of_the_shortcut(relay, callback_id, anonymous):
    run(relay, callback_id, payload())

    assert relay["handoffs"] == [(7, 41, anonymous, AUTHOR, case.SHORTCUT)]


def test_report_records_thread_root_and_reported_message_as_forward(relay):
    run(relay, shortcut.REPORT_WITH_NAME, payload(thread_ts="1792379000.000100"))

    outbound, inbound = relay["recorded"]
    assert outbound[0] == "outbound" and outbound[1]["ts"] == ROOT_TS and outbound[1]["subtype"] == consent.DONE
    assert inbound[0] == "inbound" and inbound[1]["thread_ts"] == ROOT_TS and inbound[1]["ts"] != ROOT_TS
    assert inbound[1]["text"] == "mmm" and inbound[1]["user"] == REPORTER
    forward = inbound[1]["attachments"][0]
    assert forward["is_share"] and forward["author_id"] == AUTHOR and forward["author_kind"] == shortcut.MEMBER
    assert forward["channel_id"] == ORIGIN and forward["ts"] == MESSAGE_TS
    assert forward["from_url"] == (f"https://hackclub.slack.com/archives/{ORIGIN}/p1792379645000100"
                                   f"?thread_ts=1792379000.000100&cid={ORIGIN}")
    assert relay["conversations"] == [(DM_CHANNEL, ROOT_TS, REPORTER)]


def test_report_updates_thread_root_with_receipt_and_answers_in_place(relay):
    slack, responder = run(relay, shortcut.REPORT_ANONYMOUS, payload())

    assert slack.calls[1][1]["text"] == SENDING
    assert slack.updates()[0]["ts"] == ROOT_TS and slack.updates()[0]["channel"] == DM_CHANNEL
    assert slack.updates()[0]["text"] == f"<@{REPORTER}>: Your report was sent to the Fire Department."
    assert responder.said == [shortcut.REPORTED]


def test_report_of_a_bot_post_has_no_subject_and_bot_author_kind(relay):
    slack = FakeSlack(users={"UBOT": {"is_bot": True}})
    run(relay, shortcut.REPORT_WITH_NAME, payload(user="UBOT", bot_id="B1"), slack)

    forward = relay["recorded"][1][1]["attachments"][0]
    assert relay["handoffs"][0][3] is None
    assert forward["author_id"] is None and forward["author_kind"] == shortcut.BOT


def test_report_of_a_webhook_post_without_user_has_no_subject(relay):
    run(relay, shortcut.REPORT_WITH_NAME, payload(user=None, subtype="bot_message", bot_id="B1"))

    assert relay["handoffs"][0][3] is None
    assert relay["recorded"][1][1]["attachments"][0]["author_kind"] == shortcut.BOT


def test_report_of_a_member_post_made_through_an_app_keeps_the_subject(relay):
    slack = FakeSlack(users={AUTHOR: {"is_bot": False}})
    run(relay, shortcut.REPORT_WITH_NAME, payload(bot_id="B1"), slack)

    assert relay["handoffs"][0][3] == AUTHOR


def test_report_of_a_bot_post_with_unknown_user_assumes_a_bot(relay):
    run(relay, shortcut.REPORT_WITH_NAME, payload(bot_id="B1"))

    assert relay["handoffs"][0][3] is None


def test_anonymous_report_of_own_message_withholds_the_author(relay):
    run(relay, shortcut.REPORT_ANONYMOUS, payload(user=REPORTER))

    forward = relay["recorded"][1][1]["attachments"][0]
    assert relay["handoffs"][0][3] is None
    assert forward["author_id"] is None and forward["author_kind"] == shortcut.WITHHELD


def test_named_report_of_own_message_has_no_subject(relay):
    run(relay, shortcut.REPORT_WITH_NAME, payload(user=REPORTER))

    assert relay["handoffs"][0][3] is None
    assert relay["recorded"][1][1]["attachments"][0]["author_id"] == REPORTER


def test_report_of_a_message_without_text_uses_placeholder(relay):
    run(relay, shortcut.REPORT_WITH_NAME, payload(text=""))

    assert relay["recorded"][1][1]["text"] == shortcut.NO_TEXT


def test_report_twice_hands_over_twice(relay):
    run(relay, shortcut.REPORT_WITH_NAME, payload())
    run(relay, shortcut.REPORT_WITH_NAME, payload())

    assert len(relay["handoffs"]) == 2


def test_report_when_dm_cannot_be_opened_hands_nothing_over(relay):
    slack, responder = run(relay, shortcut.REPORT_WITH_NAME, payload(), FakeSlack(fail="open"))

    assert relay["handoffs"] == [] and relay["recorded"] == []
    assert responder.said == [SUBMIT_FAILED]


def test_report_when_hand_over_fails_marks_the_thread_and_answers(relay):
    relay["fail_handoff"] = True
    slack, responder = run(relay, shortcut.REPORT_WITH_NAME, payload())

    assert slack.updates()[0]["text"] == SUBMIT_FAILED
    assert responder.said == [SUBMIT_FAILED]


def test_report_without_message_is_not_reportable(relay):
    body = payload()
    body["message"] = {}
    slack, responder = run(relay, shortcut.REPORT_WITH_NAME, body)

    assert responder.said == [shortcut.NOT_REPORTABLE] and slack.calls == []


def test_open_case_with_subject_adds_participant_once(monkeypatch):
    class Conn:
        def __init__(self):
            self.statements = []

        def execute(self, sql, args=None):
            self.statements.append((sql, args))
            return self

        def fetchone(self):
            sql = self.statements[-1][0]
            if sql == case.ADD_SUBJECT:
                return ("UAUTHOR",)
            return (1,)

    audited = []
    monkeypatch.setattr(case.audit, "record", lambda *args, **kwargs: audited.append((args, kwargs)))
    conn = Conn()

    assert case.add_subject(conn, 5, "UAUTHOR", "UBOT") is True
    assert audited[0][0][1:5] == ("participant", 5, "attached", "UBOT")
    assert audited[0][1]["after"] == {"user_id": "UAUTHOR", "role": "subject"}


class CaseConn:
    def __init__(self):
        self.statements = []

    def execute(self, sql, args=None):
        self.statements.append((sql, args))
        return self

    def fetchone(self):
        sql = self.statements[-1][0]
        if sql == case.CONVERSATION:
            return (None, None, REPORTER)
        if sql == case.FIRST_INBOUND:
            return ("mmm", None)
        if sql == case.ADD_SUBJECT:
            return (AUTHOR,)
        return (9,)


def test_open_case_stores_entry_point_and_adds_the_subject(monkeypatch):
    monkeypatch.setattr(case.audit, "record", lambda *args, **kwargs: None)
    conn = CaseConn()

    assert case.open_case(conn, 7, "UBOT", False, AUTHOR, case.SHORTCUT) == 9

    report = next(one for one in conn.statements if "INSERT INTO fd.case_reports" in one[0])
    assert report[1][-1] == case.SHORTCUT and report[1][2] == REPORTER
    assert (case.ADD_SUBJECT, (9, AUTHOR)) in conn.statements


def test_open_case_without_subject_defaults_to_dm_and_adds_no_participant(monkeypatch):
    monkeypatch.setattr(case.audit, "record", lambda *args, **kwargs: None)
    conn = CaseConn()

    case.open_case(conn, 7, "UBOT")

    report = next(one for one in conn.statements if "INSERT INTO fd.case_reports" in one[0])
    assert report[1][-1] == case.DM
    assert all(one[0] != case.ADD_SUBJECT for one in conn.statements)
