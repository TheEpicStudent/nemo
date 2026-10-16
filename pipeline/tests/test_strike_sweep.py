import contextlib

from bot.nemo import guard_actions, guards


def test_users_over_threshold_query_takes_live_guards_under_the_cap():
    sql = guards.USERS_OVER_THRESHOLD
    assert "g.state IN ('warned', 'running')" in sql
    assert "%(cap)s = 0 OR" in sql
    assert "reset_outcome IN ('reset', 'would')" in sql
    assert "HAVING count(*) >= %(needed)s" in sql


class FakeConn:
    def __init__(self):
        self.args = None

    def execute(self, sql, args=None):
        self.args = args
        return self

    def fetchall(self):
        return []


def test_users_over_threshold_passes_needed_and_cap():
    conn = FakeConn()

    assert guards.users_over_threshold(conn, 3, 5) == []
    assert conn.args == {"needed": 3, "cap": 5}


def test_sweep_strikes_reads_the_cap_setting(monkeypatch):
    seen = []

    @contextlib.contextmanager
    def fake_session():
        yield object()

    monkeypatch.setattr(guard_actions, "session", fake_session)
    monkeypatch.setattr(guard_actions.privileged, "strikes_needed", lambda conn=None: 2)
    monkeypatch.setattr(guard_actions.privileged, "cap_per_guard", lambda conn=None: 5)
    monkeypatch.setattr(guard_actions.guards, "users_over_threshold",
                        lambda conn, needed, cap: seen.append((needed, cap)) or [])

    assert guard_actions.sweep_strikes() == 0
    assert seen == [(2, 5)]
