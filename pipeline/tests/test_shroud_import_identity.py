import pytest
from slack_sdk.errors import SlackApiError

from jobs import shroud_identity, shroud_import
from jobs.shroud_identity import ANONYMOUS, AUTO, NAMED, PROMPT, SHORTCUT, UNKNOWN


def api_error(error):
    return SlackApiError(f"The request failed: {error}", {"ok": False, "error": error})


class Client:
    def __init__(self, pages=None, error=None):
        self.pages = list(pages or [])
        self.error = error
        self.calls = []

    def conversations_history(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.pages.pop(0) if self.pages else {"messages": []}


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(shroud_identity.time, "sleep", lambda seconds: None)


def test_kind_of_tells_auto_forwards_prompts_and_shortcuts_apart():
    assert shroud_identity.kind_of(True, "1.0") == AUTO
    assert shroud_identity.kind_of(False, "1.0") == PROMPT
    assert shroud_identity.kind_of(False, "") == SHORTCUT
    assert shroud_identity.kind_of(False, None) == SHORTCUT


def test_shortcut_reporter_reads_the_reported_by_line():
    named = "\U0001F6A9 New report on a message from <@UAUTHOR> in <#C1>\nReported by <@UREPORTER>\n>hi"
    emoji_name = ":triangular_flag_on_post: New report on a message in <#C1>\nReported by <@UREPORTER>"
    anonymous = "\U0001F6A9 New report on a message from <@UAUTHOR> in <#C1>\n>Reported by <@UFAKE>"

    assert shroud_identity.shortcut_reporter(named) == "UREPORTER"
    assert shroud_identity.shortcut_reporter(emoji_name) == "UREPORTER"
    assert shroud_identity.shortcut_reporter(anonymous) is None
    assert shroud_identity.shortcut_reporter("Reported by <@UREPORTER>") is None


def test_forward_choice_follows_what_slack_showed():
    assert shroud_identity.forward_choice(PROMPT, None) == (UNKNOWN, None)
    assert shroud_identity.forward_choice(
        PROMPT, {"metadata": {"event_payload": {"source_user_id": "U1"}}, "username": "Pat"}) == (NAMED, "U1")
    assert shroud_identity.forward_choice(PROMPT, {"username": "Pat", "subtype": "bot_message"}) == (NAMED, None)
    assert shroud_identity.forward_choice(PROMPT, {"bot_id": "B1", "text": "hi"}) == (ANONYMOUS, None)
    assert shroud_identity.forward_choice(AUTO, {"bot_id": "B1", "text": "hi"}) == (NAMED, None)


def test_forward_choice_never_names_a_shortcut_from_its_username():
    message = {"username": "Pat", "text": "\U0001F6A9 New report on a message in <#C1>"}

    assert shroud_identity.forward_choice(SHORTCUT, message) == (ANONYMOUS, None)


def test_human_author_ignores_bot_messages():
    assert shroud_identity.human_author({"user": "U1"}) == "U1"
    assert shroud_identity.human_author({"user": "UBOT", "bot_id": "B1"}) is None
    assert shroud_identity.human_author({"user": "U1", "subtype": "bot_message"}) is None
    assert shroud_identity.human_author(None) is None


def test_messages_one_skips_a_client_that_cannot_read_the_channel():
    blind = Client(error=api_error("channel_not_found"))
    sighted = Client([{"messages": [{"ts": "2.2", "username": "Pat"}]}])
    messages = shroud_identity.Messages([blind, None, sighted])

    assert messages.one("G1", "2.2") == {"ts": "2.2", "username": "Pat"}
    assert messages.one("G1", "2.2") == {"ts": "2.2", "username": "Pat"}
    assert len(sighted.calls) == 1
    assert sighted.calls[0]["include_all_metadata"] is True


def test_messages_one_marks_a_channel_nobody_can_read():
    messages = shroud_identity.Messages([Client(error=api_error("not_in_channel"))])

    assert messages.one("G1", "2.2") is None
    assert messages.unreadable == {"G1"}


def test_messages_one_raises_other_slack_errors():
    messages = shroud_identity.Messages([Client(error=api_error("ratelimited"))])

    with pytest.raises(SlackApiError):
        messages.one("C1", "2.2")


def test_messages_channel_pages_and_keeps_only_wanted_messages():
    client = Client([
        {"messages": [{"ts": "3.0"}, {"ts": "2.0"}], "response_metadata": {"next_cursor": "next"}},
        {"messages": [{"ts": "1.0", "username": "Pat"}]},
    ])
    messages = shroud_identity.Messages([client])

    assert messages.channel("C1", "1.0", "3.0", {"1.0", "3.0"}) is True
    assert messages.get("C1", "1.0") == {"ts": "1.0", "username": "Pat"}
    assert messages.known("C1", "3.0") and not messages.known("C1", "2.0")
    assert [call.get("cursor") for call in client.calls] == [None, "next"]


class Forwards:
    def __init__(self, message):
        self.message = message
        self.unreadable = set()

    def one(self, channel_id, ts):
        return self.message


class Dms:
    def __init__(self, message):
        self.message = message
        self.calls = 0

    def one(self, channel_id, ts):
        self.calls += 1
        return self.message


def test_decide_names_a_prompt_report_from_the_dm_author_once_per_dm():
    dms = Dms({"user": "UREPORTER"})
    identity = shroud_identity.Identity(Forwards(None), dms)

    assert identity.decide(PROMPT, {"username": "Pat"}, "D1", "1.0") == (NAMED, "UREPORTER")
    assert identity.decide(PROMPT, {"username": "Pat"}, "D1", "1.5") == (NAMED, "UREPORTER")
    assert dms.calls == 1


def test_decide_prefers_a_reporter_nemo_already_knows():
    dms = Dms({"user": "UOTHER"})
    identity = shroud_identity.Identity(Forwards(None), dms)

    assert identity.decide(PROMPT, {"username": "Pat"}, "D1", "1.0", "UKNOWN") == (NAMED, "UKNOWN")
    assert dms.calls == 0


def test_decide_leaves_a_named_report_unknown_when_the_dm_was_written_by_a_bot():
    identity = shroud_identity.Identity(Forwards(None), Dms({"user": "USHROUD", "bot_id": "B1"}))

    assert identity.decide(PROMPT, {"username": "Pat"}, "D1", "1.0") == (UNKNOWN, None)


def test_decide_names_a_shortcut_only_from_its_reported_by_line():
    dms = Dms({"user": "UREPORTER"})
    identity = shroud_identity.Identity(Forwards(None), dms)
    named = {"text": "\U0001F6A9 New report on a message in <#C1>\nReported by <@UNAMED>"}
    anonymous = {"text": "\U0001F6A9 New report on a message in <#C1>"}

    assert identity.decide(SHORTCUT, named, "D1", "1.0") == (NAMED, "UNAMED")
    assert identity.decide(SHORTCUT, anonymous, "D1", "1.0") == (ANONYMOUS, None)
    assert dms.calls == 0


def test_decide_keeps_an_anonymous_forward_anonymous():
    dms = Dms({"user": "UREPORTER"})
    identity = shroud_identity.Identity(Forwards(None), dms)

    assert identity.decide(PROMPT, {"bot_id": "B1", "text": "hi"}, "D1", "1.0", "UKNOWN") == (ANONYMOUS, None)
    assert dms.calls == 0


class Conn:
    def __init__(self, answers):
        self.answers = answers
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        self.last = sql
        return self

    def fetchone(self):
        for mark, row in self.answers.items():
            if mark in self.last:
                return row() if callable(row) else row
        return None

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


def forwarded(conn, identity, **over):
    values = {"report_id": 9, "dm_ts": "1.1", "dm_channel": "D1", "forwarded_ts": "2.2",
              "selection_ts": "1.2", "content": "hi", "reply_time": None, "auto_forward": False,
              "created_at": None}
    values.update(over)
    importer = shroud_import.Import(identity)
    importer.forwarded(conn, **values)
    return importer


def new_report_conn():
    conversation_rows = iter([(31, None)])
    return Conn({
        "FROM fd.cases WHERE card_thread_ts": (77, "C0FIRE", None, None),
        "FROM fd.case_reports WHERE external_ref": None,
        "SELECT id, report_id FROM fd.intake_conversations": lambda: next(conversation_rows),
        "INSERT INTO fd.case_reports": (501,),
        "INSERT INTO fd.intake_messages": (601, True),
    })


def test_new_import_names_a_report_whose_forward_was_impersonated(monkeypatch):
    monkeypatch.setattr(shroud_import, "ensure_member", lambda conn, user_id: None)
    conn = new_report_conn()
    identity = shroud_identity.Identity(Forwards({"username": "Pat"}), Dms({"user": "UREPORTER"}))

    forwarded(conn, identity)

    report = conn.args_for("INSERT INTO fd.case_reports")[0]
    assert report[1:3] == ("UREPORTER", False)
    assert conn.args_for("INSERT INTO fd.intake_conversations")[0][2] == "UREPORTER"


def test_new_import_keeps_a_plain_forward_anonymous(monkeypatch):
    monkeypatch.setattr(shroud_import, "ensure_member", lambda conn, user_id: None)
    conn = new_report_conn()
    dms = Dms({"user": "UREPORTER"})
    identity = shroud_identity.Identity(Forwards({"bot_id": "B1", "text": "hi"}), dms)

    forwarded(conn, identity)

    report = conn.args_for("INSERT INTO fd.case_reports")[0]
    assert report[1:3] == (None, True)
    assert report[5:7] == (None, None)
    assert conn.args_for("INSERT INTO fd.intake_conversations")[0][2] is None


def test_new_import_stores_the_shared_message_of_the_dm(monkeypatch):
    monkeypatch.setattr(shroud_import, "ensure_member", lambda conn, user_id: None)
    conn = new_report_conn()
    share = {"is_share": True, "channel_id": "C1", "ts": "1.1", "author_id": "UAUTHOR", "text": "spam"}
    identity = shroud_identity.Identity(Forwards({"bot_id": "B1", "text": "hi"}),
                                        Dms({"user": "UREPORTER", "attachments": [share]}))

    forwarded(conn, identity)

    stored = conn.args_for("INSERT INTO fd.intake_shares")
    assert len(stored) == 1
    assert stored[0][0] == 601 and stored[0][6] == "UAUTHOR"


def test_forwarded_with_dm_files_marks_files_posted_and_notified(monkeypatch):
    monkeypatch.setattr(shroud_import, "ensure_member", lambda conn, user_id: None)
    conn = new_report_conn()
    conn.answers["INSERT INTO fd.intake_files"] = (701,)
    file = {"id": "F1", "name": "shot.png", "user": "UREPORTER", "mimetype": "image/png",
            "url_private": "https://files.slack.com/files-pri/T1-F1/shot.png"}
    identity = shroud_identity.Identity(Forwards({"username": "Pat"}),
                                        Dms({"user": "UREPORTER", "files": [file]}))

    forwarded(conn, identity)

    assert conn.args_for("INSERT INTO fd.intake_message_files")
    assert conn.args_for("mirrored_file_id = f.slack_file_id") == [(601,)]
    assert conn.args_for("SET reporter_notified_at = now()") == [(601,)]


def test_an_existing_report_is_left_alone():
    conn = Conn({"FROM fd.cases WHERE card_thread_ts": (77, "C0FIRE", None, None),
                 "FROM fd.case_reports WHERE external_ref": (501, 77)})
    importer = forwarded(conn, shroud_identity.Identity(Forwards(None), Dms(None)))

    assert importer.summary == {"already": 1}
    assert len(conn.executed) == 2
