import contextlib

from bot.core import intake
from bot.relay import messages


class FakeConn:
    def __init__(self, renamed=()):
        self.renamed = list(renamed)
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return [(file_id,) for file_id in self.renamed]


def test_rename_anonymous_files_returns_updated_file_ids():
    conn = FakeConn(renamed=[119, 120])

    assert intake.rename_anonymous_files(conn, 7) == [119, 120]
    assert conn.executed == [(intake.RENAME_ANONYMOUS_FILES, (7,))]


def test_rename_anonymous_files_query_scopes_to_anonymous_inbound_files():
    sql = intake.RENAME_ANONYMOUS_FILES
    assert "r.is_anonymous" in sql
    assert "m.direction = 'inbound'" in sql
    assert "c.id = %s" in sql
    assert "SET name = ('file-' || f.id ||" in sql
    assert "title = NULL" in sql


def test_submit_report_anonymous_renames_files_after_opening_case(monkeypatch):
    calls = []

    @contextlib.contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(messages, "session", fake_session)
    monkeypatch.setattr(messages, "bot_user_id", lambda client, name: "URELAY")
    monkeypatch.setattr(messages.case, "existing", lambda conn, conversation_id: None)
    monkeypatch.setattr(messages.case, "open_case",
                        lambda conn, conversation_id, opener, anonymous, subject_user_id=None, entry_point="dm":
                            calls.append(("open", anonymous)) or 512)
    monkeypatch.setattr(messages.intake, "rename_anonymous_files",
                        lambda conn, conversation_id: calls.append(("rename", conversation_id)) or [])
    monkeypatch.setattr(messages.evidence, "promote",
                        lambda conn, case_id, conversation_id, opener: {"threads": 0, "messages": 0})
    relay = messages.MessageRelay()
    monkeypatch.setattr(relay, "fetch_attachments", lambda conversation_id: 0)

    assert relay.submit_report(7, 41, anonymous=True) == 512
    assert calls == [("open", True), ("rename", 7)]


class StateConn:
    def __init__(self, results):
        self.results = results
        self.sql = None

    def execute(self, sql, args=None):
        self.sql = sql
        return self

    def fetchone(self):
        return self.results.get(self.sql)


class FakeApp:
    def __init__(self):
        self.events = {}

    def event(self, name):
        return lambda handler: self.events.setdefault(name, handler)

    def action(self, name):
        return lambda handler: handler


def test_dm_on_message_follow_up_renames_files_for_conversation(monkeypatch):
    from bot.relay import dm

    renamed = []
    results = {dm.TRUSTED_SENDERS: ("",), dm.CONVERSATION_STATE: (True, None, None)}

    @contextlib.contextmanager
    def fake_session():
        yield StateConn(results)

    monkeypatch.setattr(dm, "session", fake_session)
    monkeypatch.setattr(dm.intake, "record", lambda conn, event: (42, True))
    monkeypatch.setattr(dm.intake, "conversation", lambda conn, channel_id, thread_ts, member=None: 7)
    monkeypatch.setattr(dm.intake, "rename_anonymous_files", lambda conn, conversation_id: renamed.append(conversation_id))
    app = FakeApp()
    dm.register(app, lambda conversation_id, message_id, anonymous=True: None)
    client = type("Client", (), {"reactions_add": lambda self, **kwargs: None})()

    app.events["message"]({"channel": "D1", "channel_type": "im", "ts": "2.0", "thread_ts": "1.0",
                           "user": "UREPORTER1", "text": "one more"}, client)

    assert renamed == [7]


def test_submit_report_downloads_files_in_the_background(monkeypatch):
    started = []

    @contextlib.contextmanager
    def fake_session():
        yield object()

    class FakeThread:
        def __init__(self, target, args, name, daemon):
            started.append((target.__name__, args, name, daemon))

        def start(self):
            started.append("started")

    monkeypatch.setattr(messages, "session", fake_session)
    monkeypatch.setattr(messages, "bot_user_id", lambda client, name: "URELAY")
    monkeypatch.setattr(messages.case, "existing", lambda conn, conversation_id: None)
    monkeypatch.setattr(messages.case, "open_case", lambda conn, conversation_id, opener, anonymous, subject_user_id=None, entry_point="dm": 512)
    monkeypatch.setattr(messages.intake, "rename_anonymous_files", lambda conn, conversation_id: [])
    monkeypatch.setattr(messages.evidence, "promote",
                        lambda conn, case_id, conversation_id, opener: {"threads": 0, "messages": 0})
    monkeypatch.setattr(messages.threading, "Thread", FakeThread)

    assert messages.MessageRelay().submit_report(7, 41) == 512
    assert started == [("fetch_attachments", (7,), "relay-files-7", True), "started"]
