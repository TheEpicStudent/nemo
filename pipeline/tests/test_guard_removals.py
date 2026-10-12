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


def throttled():
    failure = RuntimeError("proxy returned 429: budget: nemo:admin:chat.delete is spent")
    failure.http_status = 429
    return failure


def run_drain(monkeypatch, conn, outcomes=None, on_settled=None):
    attempts = []
    outcomes = dict(outcomes or {})

    def remove(client, channel_id, ts, max_retries=2):
        attempts.append((ts, max_retries))
        if ts in outcomes:
            raise outcomes[ts]
        return True

    monkeypatch.setattr(guard_removals, "session", lambda: _conn_context(conn))
    monkeypatch.setattr(guard_removals.guard_actions, "remove", remove)
    more_pending = guard_removals.drain(object(), on_settled)
    return attempts, more_pending


def pending(*ts):
    return [(n, CHANNEL_ID, one) for n, one in enumerate(ts, start=1)]


def test_queued_deletes_are_retried_without_sleeping(monkeypatch):
    conn = Conn(pending("1.1", "1.2"))
    wake_calls = []

    attempts, more_pending = run_drain(monkeypatch, conn, on_settled=lambda: wake_calls.append(1))

    assert attempts == [("1.1", 0), ("1.2", 0)]
    assert conn.args_for("SET remove_pending = false, detail = NULL") == [(1,), (2,)]
    assert wake_calls == [1]
    assert more_pending is False


def test_a_rate_limit_stops_the_pass_without_spending_an_attempt(monkeypatch):
    conn = Conn(pending("1.1", "1.2", "1.3"))

    attempts, more_pending = run_drain(monkeypatch, conn, {"1.2": throttled()})

    assert [ts for ts, _ in attempts] == ["1.1", "1.2"]
    assert conn.args_for("SET remove_pending = false, detail = NULL") == [(1,)]
    assert not conn.args_for("remove_attempts = remove_attempts + 1")
    assert more_pending is False


def test_another_failure_spends_an_attempt_and_keeps_going(monkeypatch):
    conn = Conn(pending("1.1", "1.2"), rows_remain=True)
    wake_calls = []

    run_drain(monkeypatch, conn, {"1.1": RuntimeError("cant_delete_message")},
              on_settled=lambda: wake_calls.append(1))

    (failed,) = conn.args_for("remove_attempts = remove_attempts + 1")
    assert failed == ("cant_delete_message", guard_removals.GIVE_UP_AFTER,
                      guard_removals.GIVE_UP_AFTER, 1)
    assert conn.args_for("SET remove_pending = false, detail = NULL") == [(2,)]
    assert wake_calls == [1]


def test_giving_up_wakes_the_notices(monkeypatch, caplog):
    conn = Conn(pending("1.1"), rows_remain=False)
    wake_calls = []
    caplog.set_level("WARNING", logger="bot.nemo")

    run_drain(monkeypatch, conn, {"1.1": RuntimeError("cant_delete_message")},
              on_settled=lambda: wake_calls.append(1))

    assert wake_calls == [1]
    assert any("gave up deleting 1.1" in one.getMessage() for one in caplog.records)


def test_a_message_already_gone_counts_as_removed(monkeypatch):
    conn = Conn(pending("1.1"))

    run_drain(monkeypatch, conn, {"1.1": RuntimeError("message_not_found")})

    assert conn.args_for("SET remove_pending = false, detail = NULL") == [(1,)]
    assert not conn.args_for("remove_attempts = remove_attempts + 1")


def test_nothing_pending_wakes_nothing(monkeypatch):
    wake_calls = []

    attempts, more_pending = run_drain(monkeypatch, Conn(), on_settled=lambda: wake_calls.append(1))

    assert attempts == []
    assert wake_calls == []
    assert more_pending is False


def test_a_full_pass_asks_for_another(monkeypatch):
    monkeypatch.setattr(guard_removals, "PER_DRAIN", 2)

    _attempts, more_pending = run_drain(monkeypatch, Conn(pending("1.1", "1.2")))

    assert more_pending is True


def test_the_claim_takes_only_queued_deletes():
    from bot.nemo import channelguards

    assert "WHERE remove_pending" in channelguards.CLAIM_REMOVALS
    assert "FOR UPDATE SKIP LOCKED" in channelguards.CLAIM_REMOVALS
