import contextlib

import pytest

from bot.nemo import case_actions, channel, command, handlers
from bot.nemo.views import merge


class App:
    def __init__(self):
        self.actions = {}
        self.views = {}

    def action(self, key):
        def register(fn):
            self.actions[getattr(key, "pattern", key)] = fn
            return fn
        return register

    def view(self, key):
        def register(fn):
            self.views[key] = fn
            return fn
        return register


class Conn:
    def __init__(self, answers):
        self.answers = answers
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        for mark, row in self.answers.items():
            if mark in self.executed[-1][0]:
                return row
        return None

    def fetchall(self):
        row = self.fetchone()
        return [row] if row else []


class Slack:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda **kwargs: self.calls.append((name, kwargs)) or {"ts": "9.9"}

    def calls_to(self, name):
        return [kwargs for method, kwargs in self.calls if method == name]


class Ack:
    def __init__(self):
        self.responses = []

    def __call__(self, **kwargs):
        self.responses.append(kwargs)


@pytest.fixture
def app(monkeypatch):
    fake_app = App()
    handlers.register(fake_app)
    conn = Conn({"resolved_at IS NULL": (True,), "category_key FROM": (None,)})

    @contextlib.contextmanager
    def fake_session():
        yield conn

    monkeypatch.setattr(handlers, "session", fake_session)
    monkeypatch.setattr(handlers.access, "may", lambda conn, user_id, capability, case=None: (True, None))
    monkeypatch.setattr(handlers, "refresh_card", lambda client, conn, case_id: None)
    return fake_app


def merge_view_state(target_id, *duplicate_ids):
    selected_options = [{"value": str(one)} for one in duplicate_ids]
    return {"state": {"values": {
        merge.TARGET: {merge.TARGET: {"selected_option": {"value": str(target_id)}}},
        merge.DUPLICATES: {merge.DUPLICATES: {"selected_options": selected_options}},
    }}}


def test_merge_view_submit_merges_duplicates_into_target_and_clears_view(app, monkeypatch):
    notes = []
    monkeypatch.setattr(handlers, "merge", lambda conn, target_id, duplicate_ids, by: duplicate_ids)
    monkeypatch.setattr(handlers, "post_merge_note",
                        lambda client, conn, target_id, closed, by: notes.append((target_id, closed, by)))
    ack = Ack()

    app.views[merge.CALLBACK](ack, {"user": {"id": "UME"}}, merge_view_state(23, 25, 31), Slack())

    assert ack.responses == [{"response_action": "clear"}]
    assert notes == [(23, [25, 31], "UME")]


def test_merge_view_same_target_and_duplicate_returns_error(app):
    ack = Ack()

    app.views[merge.CALLBACK](ack, {"user": {"id": "UME"}}, merge_view_state(23, 23), Slack())

    assert ack.responses[0]["errors"] == {merge.DUPLICATES: "A case cannot be merged into itself."}


def test_parse_case_ids_returns_target_and_duplicates():
    assert merge.parse_case_ids("23 25, #31") == (23, [25, 31])
    assert merge.parse_case_ids("") == (None, [])
    assert command.parse_command("merge 23 25") == ("merge", None, "23 25")
    assert command.NEEDED[command.MERGE] == "case.resolve"


def test_merge_sets_duplicate_of_on_duplicates_and_writes_audit_rows():
    conn = Conn({"duplicate_of = %s": ("2026-10-11",)})

    assert case_actions.merge(conn, 23, [31, 25], "UME") == [25, 31]

    duplicate_updates = [args for sql, args in conn.executed if "duplicate_of = %s" in sql]
    assert duplicate_updates == [(23, 25, 23), (23, 31, 23)]
    audit_rows = [args for sql, args in conn.executed if "audit" in sql.lower()]
    assert len(audit_rows) == 2


def test_merge_resolved_case_returns_empty_list():
    assert case_actions.merge(Conn({}), 23, [25], "UME") == []


def test_post_merge_note_posts_to_target_and_duplicate_cases(monkeypatch):
    posted_lines = []
    monkeypatch.setattr(channel, "post_line",
                        lambda client, conn, case_id, text: posted_lines.append((case_id, text)))
    monkeypatch.setattr(channel, "case_url", lambda case_id: None)

    channel.post_merge_note(None, None, 39, [25, 31], "UME")

    assert posted_lines == [
        (39, "<@UME> merged cases 25 and 31 into case 39 (this case)"),
        (25, "<@UME> merged case 25 (this case) into case 39"),
        (31, "<@UME> merged case 31 (this case) into case 39"),
    ]


def test_post_pending_resolutions_posts_only_due_cases(monkeypatch):
    from bot.nemo import case_channel

    posted = []

    @contextlib.contextmanager
    def fake_session():
        yield Conn({})

    monkeypatch.setattr(case_channel, "session", fake_session)
    monkeypatch.setattr(case_channel.case_actions, "pending_resolution_logs", lambda conn: [23, 24])
    monkeypatch.setattr(case_channel.case_actions, "resolution_log_due",
                        lambda conn, case_id: ("UME", "no_action", None) if case_id == 23 else None)
    monkeypatch.setattr(case_channel.case_actions, "resolution_log_actions", lambda conn, case_id: [])
    monkeypatch.setattr(case_channel.channel, "post_resolution_log",
                        lambda client, conn, case_id, resolution, note, by, actions:
                        posted.append((case_id, resolution, by)))

    case_channel.CaseChannel(Slack()).post_pending_resolutions()

    assert posted == [(23, "no_action", "UME")], "24 still waits on its reporter message"


def test_resolution_log_due_excludes_cases_with_pending_outcome_echo():
    assert "o.kind = 'outcome' AND o.echoed_at IS NULL" in case_actions.RESOLUTION_LOG_DUE
    assert "SET resolution_echo_by = NULL" in case_actions.RESOLUTION_LOG_DUE
