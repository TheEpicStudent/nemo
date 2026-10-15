import datetime as dt

from bot.core import case as core_case
from bot.nemo import case_actions

CASE_ID = 41
REPORT_ID = 31
MODERATOR_ID = "UMODERATOR"
REPORTER_ID = "UREPORTER"
CLOSED_AT = dt.datetime(2026, 10, 1, 12, 0, tzinfo=dt.UTC)

CASE_RESOLUTION = "SELECT resolved_at, resolution, duplicate_of"
SLACK_REOPEN = "RETURNING resolution"
CLEAR_ASSIGNEES = "DELETE FROM fd.case_assignees"
REOPEN_REPORTS = "UPDATE fd.case_reports r"
AUDIT_INSERT = "INSERT INTO fd.audit"


class Conn:
    def __init__(self, fetchone_rows=None, fetchall_rows=None):
        self.fetchone_rows = fetchone_rows or {}
        self.fetchall_rows = fetchall_rows or {}
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        return self.match(self.fetchone_rows)

    def fetchall(self):
        return self.match(self.fetchall_rows) or []

    def match(self, rows):
        sql = self.executed[-1][0]
        for marker, row in rows.items():
            if marker in sql:
                return row
        return None

    def args_for(self, marker):
        return [args for sql, args in self.executed if marker in sql]

    def report_audits(self):
        return [args for args in self.args_for(AUDIT_INSERT) if args[2] == "report"]


def closed_report_rows():
    return {REOPEN_REPORTS: [(REPORT_ID, CLOSED_AT, MODERATOR_ID)], CLEAR_ASSIGNEES: []}


def test_reporter_reopen_clears_closed_reports():
    conn = Conn({CASE_RESOLUTION: (CLOSED_AT, "action_taken", None)}, closed_report_rows())

    assert core_case.reopen(conn, CASE_ID, REPORTER_ID) == "action_taken"
    assert conn.args_for(REOPEN_REPORTS) == [(CASE_ID,)]
    assert [(args[3], args[4]) for args in conn.report_audits()] == [(REPORT_ID, "reopened")]


def test_slack_reopen_clears_closed_reports():
    conn = Conn({SLACK_REOPEN: ("action_taken",)}, closed_report_rows())

    assert case_actions.reopen(conn, CASE_ID, MODERATOR_ID) is True
    assert conn.args_for(REOPEN_REPORTS) == [(CASE_ID,)]
    assert [(args[3], args[4]) for args in conn.report_audits()] == [(REPORT_ID, "reopened")]


def test_reopen_reports_audits_previous_closure():
    conn = Conn(fetchall_rows=closed_report_rows())

    assert core_case.reopen_reports(conn, CASE_ID, MODERATOR_ID) == [REPORT_ID]

    audit_args = conn.report_audits()[0]
    assert audit_args[0] == MODERATOR_ID
    assert audit_args[5].obj == {"closed_at": str(CLOSED_AT), "closed_by": MODERATOR_ID}
    assert audit_args[6].obj == {"closed_at": None, "closed_by": None, "case_id": CASE_ID}


def test_reopen_without_closed_reports_writes_no_report_audit():
    conn = Conn({SLACK_REOPEN: ("no_action",)}, {REOPEN_REPORTS: [], CLEAR_ASSIGNEES: []})

    assert case_actions.reopen(conn, CASE_ID, MODERATOR_ID) is True
    assert conn.report_audits() == []


def test_reopen_of_open_case_leaves_reports_alone():
    conn = Conn({CASE_RESOLUTION: (None, None, None)}, closed_report_rows())

    assert core_case.reopen(conn, CASE_ID, REPORTER_ID) is None
    assert conn.args_for(REOPEN_REPORTS) == []
