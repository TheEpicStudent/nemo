import contextlib

import pytest
from slack_sdk.errors import SlackApiError

from jobs import import_repair, shroud_identity
from jobs.shroud_identity import PROMPT, SHORTCUT
from lyla.mapping import LYLA_BOT_USER_ID


@pytest.fixture(autouse=True)
def no_pause(monkeypatch):
    monkeypatch.setattr(import_repair.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(shroud_identity.time, "sleep", lambda seconds: None)


def test_header_number_reads_lylas_case_line():
    assert import_repair.header_number("Case #\u200c5053") == 5053
    assert import_repair.header_number("Case #5053") == 5053
    assert import_repair.header_number("@sunshine merged this case (#5053) into #5055") is None


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Conn:
    def __init__(self, answers):
        self.answers = answers
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        for mark, rows in self.answers.items():
            if mark in sql:
                return Rows(rows(args) if callable(rows) else rows)
        return Rows([])


class Forwards:
    def __init__(self, messages, unreadable=()):
        self.messages = messages
        self.unreadable = set(unreadable)
        self.paged = []

    def channel(self, channel_id, oldest, latest, wanted):
        self.paged.append((channel_id, oldest, latest, sorted(wanted)))

    def get(self, channel_id, ts):
        return self.messages.get(ts)


class Dms:
    def one(self, channel_id, ts):
        return {"user": "UDM"}


def report(report_id, shroud_id, anonymous=True, reporter=None, ts="2.0", channel="C0FIRE", known=None):
    return (report_id, 77, shroud_id, anonymous, reporter, channel, ts, 300 + report_id, known)


def test_plan_identity_sorts_reports_by_what_their_forward_shows():
    conn = Conn({"FROM fd.case_reports r": [
        report(1, 11, ts="1.0"),
        report(2, 12, ts="2.0"),
        report(3, 13, anonymous=False, reporter="UDM", ts="3.0"),
        report(4, 14, anonymous=False, reporter="UOLD", ts="4.0"),
        report(5, 15, ts="5.0"),
        report(6, 16, ts="6.0", channel="G0PRIVATE"),
        report(7, 17, ts="7.0"),
    ]})
    shroud = Conn({"FROM reports": [
        (11, "D1", "1.0", "1.1", False), (12, "D2", "2.0", "2.1", False), (13, "D3", "3.0", "3.1", False),
        (14, "D4", "4.0", "4.1", False), (15, "D5", "5.0", "", False), (16, "D6", "6.0", "6.1", False),
    ]})
    forwards = Forwards({
        "1.0": {"username": "Pat"},
        "2.0": {"bot_id": "B1", "text": "hi"},
        "3.0": {"username": "Pat"},
        "4.0": {"bot_id": "B1", "text": "hi"},
        "5.0": {"text": "\U0001F6A9 New report on a message in <#C1>\nReported by <@USHORT>"},
    }, unreadable={"G0PRIVATE"})
    identity = shroud_identity.Identity(forwards, Dms())

    plan = import_repair.plan_identity(conn, shroud, identity)

    assert [(one["report_id"], one["reporter"], one["kind"]) for one in plan["to_name"]] == [
        (1, "UDM", PROMPT), (5, "USHORT", SHORTCUT)]
    assert plan["already_anonymous"] == [2]
    assert plan["already_named"] == [3]
    assert [one["report_id"] for one in plan["to_anonymize"]] == [4]
    assert plan["unreadable_channel"] == [6]
    assert plan["no_shroud_row"] == [7]
    assert ("C0FIRE", "1.0", "7.0") in [paged[:3] for paged in forwards.paged]


@contextlib.contextmanager
def fake_session(conn):
    yield conn


def test_apply_identity_names_the_report_its_conversation_and_imported_messages(monkeypatch):
    conn = Conn({})
    conn.execute = lambda sql, args=None, conn=conn: (conn.executed.append((sql, args)) or
                                                     type("R", (), {"rowcount": 1})())
    members = []
    monkeypatch.setattr(import_repair, "session", lambda: fake_session(conn))
    monkeypatch.setattr(import_repair, "ensure_member", lambda c, user_id: members.append(user_id))
    entry = {"report_id": 1, "case_id": 77, "conversation_id": 301, "reporter": "UDM",
             "dm_channel": "D1", "dm_ts": "1.0", "kind": PROMPT}

    done = import_repair.apply_identity({"to_name": [entry]})

    statements = [sql for sql, _args in conn.executed]
    assert done == {"named": 1} and members == ["UDM"]
    assert any("set_config" in sql for sql in statements)
    assert any("UPDATE fd.case_reports" in sql and "is_anonymous = false" in sql for sql in statements)
    assert any("UPDATE fd.intake_conversations" in sql for sql in statements)
    assert any("UPDATE fd.intake_messages" in sql and "subtype = 'imported'" in sql for sql in statements)


def test_apply_identity_restores_anonymity(monkeypatch):
    conn = Conn({})
    conn.execute = lambda sql, args=None, conn=conn: (conn.executed.append((sql, args)) or
                                                     type("R", (), {"rowcount": 1})())
    monkeypatch.setattr(import_repair, "session", lambda: fake_session(conn))

    done = import_repair.apply_identity({"to_anonymize": [{"report_id": 4}]})

    statements = [sql for sql, _args in conn.executed]
    assert done == {"anonymized": 1}
    assert any("is_anonymous = true" in sql and "reporter_user_id = NULL" in sql for sql in statements)


def chain(parents):
    return lambda args: [(parents.get(args[0]),)] if args[0] in parents else []


def test_reaches_follows_merges_to_the_surviving_case():
    conn = Conn({"SELECT duplicate_of FROM fd.cases": chain({3263: 3264, 3264: 3261, 3261: 3251, 3251: None})})

    assert import_repair.reaches(conn, 3263, 3251) is True
    assert import_repair.reaches(conn, 3251, 3263) is False
    assert import_repair.reaches(conn, 9999, 3251) is False


class Threads:
    def __init__(self, headers):
        self.headers = headers
        self.asked = []

    def header(self, channel_id, thread_ts):
        self.asked.append(thread_ts)
        return self.headers.get(thread_ts)


def test_plan_reports_moves_reports_back_to_the_case_lyla_opened_on_their_thread():
    conn = Conn({
        "FROM fd.case_chat": [("C0FIRE", "1.0", "Case #\u200c5053"), ("C0FIRE", "3.0", "Case #\u200c5055")],
        "FROM fd.case_reports r": [(1735, 5055, "C0FIRE", "1.0"), (1736, 5055, "C0FIRE", "2.0"),
                                   (1737, 5055, "C0FIRE", "3.0"), (1800, 5055, "C0FIRE", "4.0"),
                                   (1801, 5055, "C0FIRE", "5.0")],
        "SELECT duplicate_of FROM fd.cases": chain({5053: 5055, 5054: 5055, 4000: None, 5055: None}),
    })
    threads = Threads({"2.0": 5054, "5.0": 4000})

    plan = import_repair.plan_reports(conn, threads)

    assert plan["to_move"] == [{"report_id": 1735, "from": 5055, "to": 5053},
                               {"report_id": 1736, "from": 5055, "to": 5054}]
    assert plan["already_home"] == [1737]
    assert plan["no_header"] == [1800]
    assert plan["header_outside_family"] == [1801]
    assert threads.asked == ["2.0", "4.0", "5.0"]


def test_apply_reports_moves_with_a_guard_and_wakes_both_cases(monkeypatch):
    conn = Conn({})
    conn.execute = lambda sql, args=None, conn=conn: (conn.executed.append((sql, args)) or
                                                     type("R", (), {"rowcount": 1})())
    monkeypatch.setattr(import_repair, "session", lambda: fake_session(conn))

    assert import_repair.apply_reports({"to_move": [{"report_id": 1735, "from": 5055, "to": 5053}]}) == {"moved": 1}

    moves = [args for sql, args in conn.executed if sql == import_repair.MOVE_REPORT]
    wakes = [args for sql, args in conn.executed if "pg_notify" in sql]
    assert moves == [(5053, 1735, 5055)]
    assert sorted(wakes) == [("5053",), ("5055",)]


class Replies:
    def __init__(self, messages=None, error=None):
        self.messages = messages or []
        self.error = error

    def conversations_replies(self, **kwargs):
        if self.error:
            raise SlackApiError("failed", {"ok": False, "error": self.error})
        return {"messages": self.messages}


def test_threads_header_reads_lylas_reply_and_skips_blind_clients():
    sighted = Replies([{"ts": "1.0", "user": "USHROUD", "text": "report"},
                       {"ts": "1.1", "user": LYLA_BOT_USER_ID, "text": "Case #\u200c5054"}])
    threads = import_repair.Threads([Replies(error="channel_not_found"), sighted])

    assert threads.header("C0FIRE", "1.0") == 5054
    assert import_repair.Threads([Replies([{"ts": "1.0", "user": "U1", "text": "hi"}])]).header("C", "1.0") is None


def test_apply_chat_deletes_copies_and_lyla_lines_in_batches(monkeypatch):
    conn = Conn({})
    conn.execute = lambda sql, args=None, conn=conn: (conn.executed.append((sql, args)) or
                                                     type("R", (), {"rowcount": len(args[0])})())
    monkeypatch.setattr(import_repair, "session", lambda: fake_session(conn))

    done = import_repair.apply_chat({"mirror_copies": [1, 2, 3], "lyla_messages": [4]}, batch=2)

    assert done == {"mirror_copies": 3, "lyla_messages": 1}
    assert [args[0] for _sql, args in conn.executed] == [[1, 2], [3], [4]]


SHARE = {"is_share": True, "channel_id": "C1", "ts": "1.1", "author_id": "UAUTHOR", "text": "spam",
         "from_url": "https://hackclub.slack.com/archives/C1/p1000000001100000"}
FILE = {"id": "F1", "name": "shot.png", "user": "UREPORTER", "mimetype": "image/png",
        "url_private": "https://files.slack.com/files-pri/T1-F1/shot.png"}


class DmMessages:
    def __init__(self, messages, unreadable=()):
        self.messages = messages
        self.unreadable = set(unreadable)

    def one(self, channel_id, ts):
        return self.messages.get(ts)


def test_plan_attachments_sorts_reports_by_what_their_dm_carried():
    rows = [(1, True, 31, 601, "D1", "1.0"), (2, False, 32, 602, "D2", "2.0"),
            (3, True, 33, 603, "D3", "3.0"), (4, True, 34, 604, "DGONE", "4.0")]
    dms = DmMessages({"1.0": {"attachments": [SHARE]}, "2.0": {"files": [FILE]},
                      "3.0": {"text": "see <https://hackclub.slack.com/archives/C1/p1000000001100000>"}},
                     unreadable={"DGONE"})

    plan = import_repair.plan_attachments(rows, dms)

    assert [entry["report_id"] for entry in plan["to_attach"]] == [1, 2]
    assert plan["with_shared_message"] == [1]
    assert plan["with_files"] == [2]
    assert plan["nothing_attached"] == [3]
    assert plan["unreadable_channel"] == [4]


def test_apply_attachments_with_anonymous_report_stores_file_without_uploader(monkeypatch):
    conn = Conn({"INSERT INTO fd.intake_files": [(701,)], "UPDATE fd.intake_files f": [(701,)]})
    monkeypatch.setattr(import_repair, "session", lambda: fake_session(conn))
    drained = []
    monkeypatch.setattr(import_repair, "drain_files", lambda token: drained.append(token) or 1)
    entry = {"report_id": 1, "anonymous": True, "conversation_id": 31, "message_id": 601,
             "message": {"user": "UREPORTER", "files": [FILE]}}

    done = import_repair.apply_attachments({"to_attach": [entry]}, "xoxb-relay")

    file_args = next(args for sql, args in conn.executed if "INSERT INTO fd.intake_files" in sql)
    assert file_args["uploaded_by"] is None
    assert any("UPDATE fd.intake_files f" in sql for sql, _args in conn.executed)
    assert done == {"attached": 1, "files_stored": 1}
    assert drained == ["xoxb-relay"]


def test_drain_files_downloads_until_no_file_is_waiting(monkeypatch):
    waiting = [[(1,)], [(2,)], []]
    conn = Conn({"FROM fd.intake_files f": lambda args: waiting.pop(0)})
    monkeypatch.setattr(import_repair, "session", lambda: fake_session(conn))
    calls = []
    monkeypatch.setattr(import_repair.intake_files, "drain", lambda token, limit: calls.append(limit) or 1)

    assert import_repair.drain_files("xoxb-relay") == 2
    assert calls == [import_repair.FILE_BATCH, import_repair.FILE_BATCH]
