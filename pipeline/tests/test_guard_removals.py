from bot.nemo import guard_removals

CHANNEL_ID = "C1"


class Conn:
    def __init__(self, pending=(), rows_remain=True):
        self.pending = list(pending)
        self.rows_remain = rows_remain
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        self.last = sql
        return self

    def fetchall(self):
        return self.pending

    def fetchone(self):
        return (self.rows_remain,)

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class _conn_context:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *failure):
        return False


def rate_limit_failure():
    failure = RuntimeError("proxy returned 429: budget: nemo:admin:chat.delete is spent")
    failure.http_status = 429
    return failure


def run_drain(monkeypatch, conn, failures_by_ts=None, on_finished=None):
    attempts = []
    failures_by_ts = dict(failures_by_ts or {})

    def remove(client, channel_id, ts, max_retries=2):
        attempts.append((ts, max_retries))
        if ts in failures_by_ts:
            raise failures_by_ts[ts]
        return True

    monkeypatch.setattr(guard_removals, "session", lambda: _conn_context(conn))
    monkeypatch.setattr(guard_removals.guard_actions, "remove", remove)
    more_pending = guard_removals.drain(object(), on_finished)
    return attempts, more_pending


def pending(*ts):
    return [(n, CHANNEL_ID, one) for n, one in enumerate(ts, start=1)]


def test_drain_with_pending_removals_clears_each_and_calls_on_finished(monkeypatch):
    conn = Conn(pending("1.1", "1.2"))
    finished_calls = []

    attempts, more_pending = run_drain(monkeypatch, conn, on_finished=lambda: finished_calls.append(1))

    assert attempts == [("1.1", 0), ("1.2", 0)]
    assert conn.args_for("SET remove_pending = false, detail = NULL") == [(1,), (2,)]
    assert finished_calls == [1]
    assert more_pending is False


def test_drain_on_rate_limit_stops_pass_without_counting_attempt(monkeypatch):
    conn = Conn(pending("1.1", "1.2", "1.3"))

    attempts, more_pending = run_drain(monkeypatch, conn, {"1.2": rate_limit_failure()})

    assert [ts for ts, _ in attempts] == ["1.1", "1.2"]
    assert conn.args_for("SET remove_pending = false, detail = NULL") == [(1,)]
    assert not conn.args_for("remove_attempts = remove_attempts + 1")
    assert more_pending is False


def test_drain_on_other_failure_counts_attempt_and_continues(monkeypatch):
    conn = Conn(pending("1.1", "1.2"), rows_remain=True)
    finished_calls = []

    run_drain(monkeypatch, conn, {"1.1": RuntimeError("cant_delete_message")},
              on_finished=lambda: finished_calls.append(1))

    (failed,) = conn.args_for("remove_attempts = remove_attempts + 1")
    assert failed == ("cant_delete_message", guard_removals.GIVE_UP_AFTER,
                      guard_removals.GIVE_UP_AFTER, 1)
    assert conn.args_for("SET remove_pending = false, detail = NULL") == [(2,)]
    assert finished_calls == [1]


def test_drain_when_attempts_exhausted_logs_warning_and_calls_on_finished(monkeypatch, caplog):
    conn = Conn(pending("1.1"), rows_remain=False)
    finished_calls = []
    caplog.set_level("WARNING", logger="bot.nemo")

    run_drain(monkeypatch, conn, {"1.1": RuntimeError("cant_delete_message")},
              on_finished=lambda: finished_calls.append(1))

    assert finished_calls == [1]
    assert any("gave up deleting 1.1" in one.getMessage() for one in caplog.records)


def test_drain_with_message_not_found_clears_remove_pending(monkeypatch):
    conn = Conn(pending("1.1"))

    run_drain(monkeypatch, conn, {"1.1": RuntimeError("message_not_found")})

    assert conn.args_for("SET remove_pending = false, detail = NULL") == [(1,)]
    assert not conn.args_for("remove_attempts = remove_attempts + 1")


def test_drain_without_pending_removals_does_not_call_on_finished(monkeypatch):
    finished_calls = []

    attempts, more_pending = run_drain(monkeypatch, Conn(), on_finished=lambda: finished_calls.append(1))

    assert attempts == []
    assert finished_calls == []
    assert more_pending is False


def test_drain_with_full_batch_returns_true(monkeypatch):
    monkeypatch.setattr(guard_removals, "PER_DRAIN", 2)

    _attempts, more_pending = run_drain(monkeypatch, Conn(pending("1.1", "1.2")))

    assert more_pending is True


def test_claim_removals_sql_selects_pending_with_skip_locked():
    from bot.nemo import channelguards

    assert "WHERE remove_pending" in channelguards.CLAIM_REMOVALS
    assert "FOR UPDATE SKIP LOCKED" in channelguards.CLAIM_REMOVALS
