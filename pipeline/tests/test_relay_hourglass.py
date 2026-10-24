import contextlib

from slack_sdk.errors import SlackApiError

from bot.relay import hourglass, loop


class Conn:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return self.rows


class Slack:
    def __init__(self, errors=None):
        self.errors = errors or {}
        self.removed = []

    def reactions_remove(self, **kwargs):
        error = self.errors.get(kwargs["timestamp"])
        if error:
            raise SlackApiError("failed", {"ok": False, "error": error})
        self.removed.append((kwargs["channel"], kwargs["timestamp"], kwargs["name"]))


def use(monkeypatch, conn):
    @contextlib.contextmanager
    def session():
        yield conn

    monkeypatch.setattr(hourglass, "session", session)


def marked(conn):
    return [args[0] for sql, args in conn.executed if sql == hourglass.REMOVED]


def test_release_removes_shrouds_hourglass_and_marks_the_report(monkeypatch):
    conn = Conn([(1, "C0FIRE", "1.0")])
    use(monkeypatch, conn)
    slack = Slack()

    assert hourglass.release(slack, 5055) == 1
    assert slack.removed == [("C0FIRE", "1.0", "hourglass")]
    assert marked(conn) == [1]
    assert conn.executed[0][1] == {"case_id": 5055, "limit": hourglass.BATCH}


def test_release_marks_reports_that_have_nothing_left_to_remove(monkeypatch):
    conn = Conn([(1, "C0FIRE", "1.0"), (2, "C0FIRE", "2.0")])
    use(monkeypatch, conn)

    hourglass.release(Slack({"1.0": "no_reaction", "2.0": "message_not_found"}))

    assert marked(conn) == [1, 2]


def test_release_retries_later_after_other_errors(monkeypatch):
    conn = Conn([(1, "C0FIRE", "1.0")])
    use(monkeypatch, conn)

    assert hourglass.release(Slack({"1.0": "ratelimited"})) == 0
    assert marked(conn) == []


def test_waiting_only_counts_cases_resolved_after_the_lyla_import():
    assert "lyla_sync_status WHERE name = 'import'" in hourglass.WAITING
    assert "hourglass_removed_at IS NULL" in hourglass.WAITING
    assert "source_app = 'shroud'" in hourglass.WAITING


def test_relay_loop_sends_case_changes_to_the_hourglass(monkeypatch):
    released, delivered, listened = [], [], {}
    relay = type("Relay", (), {"client": object(), "deliver": lambda self, cid: delivered.append(cid)})()
    monkeypatch.setattr(loop.hourglass, "release", lambda client, case_id=None: released.append(case_id))
    monkeypatch.setattr(loop.loops, "start_listener",
                        lambda name, names, on_notify, stopping: listened.update(names=names, notify=on_notify))
    monkeypatch.setattr(loop.loops, "run_periodically", lambda *args, **kwargs: None)

    loop.start(relay, None)
    listened["notify"](loop.CASES, 5055)
    listened["notify"](loop.OUTBOX, 12)

    assert loop.CASES in listened["names"]
    assert released == [5055] and delivered == [12]
