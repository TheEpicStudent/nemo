import re
import inspect
from unittest import mock

import pytest

from lib import work


def test_outcome_after_failure_at_max_attempts_returns_dead():
    assert work.outcome_after_failure(1) == "pending"
    assert work.outcome_after_failure(work.MAX_ATTEMPTS - 1) == "pending"
    assert work.outcome_after_failure(work.MAX_ATTEMPTS) == "dead"
    assert work.outcome_after_failure(2, max_attempts=2) == "dead"


def test_outcome_after_lapse_at_max_lapses_returns_dead():
    assert work.outcome_after_lapse(0) == "pending"
    assert work.outcome_after_lapse(work.MAX_LAPSES - 2) == "pending"
    assert work.outcome_after_lapse(work.MAX_LAPSES - 1) == "dead"
    assert work.outcome_after_lapse(1, max_lapses=2) == "dead"
    assert work.MAX_LAPSES > work.MAX_ATTEMPTS


def test_revivable_at_max_revivals_returns_false():
    assert work.revivable(0)
    assert work.revivable(work.MAX_REVIVALS - 1)
    assert not work.revivable(work.MAX_REVIVALS)
    assert not work.revivable(4742)
    assert "attempts < %(max_revivals)s" in work.CONFLICT_GROWN
    assert work.MAX_REVIVALS > work.MAX_ATTEMPTS


def test_reclaim_sql_decrements_attempts_and_increments_lapses():
    assert "attempts = greatest(attempts - 1, 0)" in work.RECLAIM_SQL
    assert "lapses = lapses + 1" in work.RECLAIM_SQL
    assert "lapses + 1 >= %(max_lapses)s" in work.RECLAIM_SQL
    assert "max_attempts" not in work.RECLAIM_SQL


def test_positional_builds_numbered_param_dict_for_enqueue_sql():
    assert work._positional(("a", 2)) == {"p0": "a", "p1": 2}
    sql = work.ENQUEUE_SQL.format(select="SELECT 1", conflict=work.CONFLICT_IGNORE)
    assert "'{}'::jsonb" in sql
    assert sql.rstrip().endswith("DO NOTHING")


def test_conflict_grown_excludes_claimed_state():
    assert "state <> 'claimed'" in work.CONFLICT_GROWN
    assert "EXCLUDED.expected > coalesce(ingest.work_item.fetched, 0)" in work.CONFLICT_GROWN


def test_conflict_grown_excludes_dead_state():
    assert "state <> 'dead'" in work.CONFLICT_GROWN


def test_revive_sql_selects_dead_items_excluding_entity_errors_and_refusals():
    assert "WHERE  state = 'dead'" in work.REVIVE_SQL
    assert "left(coalesce(last_error, ''), 7) <> 'entity:'" in work.REVIVE_SQL
    assert "<> ALL(%(refusals)s::text[])" in work.REVIVE_SQL


def test_instance_lock_uses_session_advisory_lock_in_singleton_namespace():
    from lib import db

    assert db.SINGLETON_NAMESPACE == 8571
    source = inspect.getsource(db.instance_lock)
    assert "pg_try_advisory_lock" in source
    assert "pg_advisory_xact_lock" not in source
    assert "pg_advisory_unlock" in source
    assert "lock_conn.close()" in source


def test_instance_lock_when_lock_taken_raises_already_running_error():
    from lib import db

    class LockTakenConn:
        def execute(self, *_args):
            return self

        def fetchone(self):
            return (False,)

        def commit(self):
            pass

        def close(self):
            self.closed = True

    conn = LockTakenConn()
    with mock.patch.object(db, "connect", lambda *a, **k: conn):
        with pytest.raises(db.AlreadyRunningError, match="holds the singleton lock"):
            with db.instance_lock("archive_worker"):
                raise AssertionError("the body must not run")
    assert getattr(conn, "closed", False)


def test_instance_lock_when_free_runs_body_then_unlocks_and_closes():
    from lib import db

    calls = []

    class FreeLockConn:
        def execute(self, sql, *_args):
            calls.append("lock" if "try_advisory" in sql else "unlock")
            return self

        def fetchone(self):
            return (True,)

        def commit(self):
            pass

        def close(self):
            calls.append("close")

    with mock.patch.object(db, "connect", lambda *a, **k: FreeLockConn()):
        with db.instance_lock("archive_worker"):
            calls.append("body")
    assert calls == ["lock", "body", "unlock", "close"]


def test_sweep_stale_runs_sql_has_two_placeholders_and_no_format():
    from lib import db

    src = inspect.getsource(db.sweep_stale_runs)
    sql = src[src.index('"""') + 3:src.rindex('"""')]
    assert sql.count("%s") == 2
    assert "format(" not in sql


def test_settle_sql_resets_attempts_when_state_complete():
    from lib import work

    sql = work.SETTLE_SQL
    assert "attempts = CASE WHEN %(state)s = 'complete' THEN 0 ELSE attempts END" in sql


def test_settle_sql_resets_attempts_with_case_not_unconditionally():
    from lib import work

    assert "THEN 0 ELSE attempts END" in work.SETTLE_SQL
    assert "attempts = 0," not in work.SETTLE_SQL


def test_settle_and_settle_many_use_settle_sql():
    from lib import work

    assert "SETTLE_SQL" in inspect.getsource(work.settle)
    assert "SETTLE_SQL" in inspect.getsource(work.settle_many)


def test_claim_fail_and_settle_sql_increment_cap_and_reset_attempts():
    from lib import work

    claim_increments_attempts = "attempts = w.attempts + 1" in work.CLAIM_SQL
    fail_checks_max_attempts = "attempts >= %(max_attempts)s" in work.FAIL_SQL
    settle_resets_attempts = "THEN 0 ELSE attempts END" in work.SETTLE_SQL
    assert claim_increments_attempts and fail_checks_max_attempts and settle_resets_attempts


def test_backoff_with_retry_spread_returns_varied_waits_within_bounds():
    from lib import lease, work

    waits = {lease.backoff(3, base=30.0, cap=6 * 3600, spread=work.RETRY_SPREAD)
             for _ in range(200)}
    assert len(waits) > 100
    assert all(240.0 <= w <= 240.0 * (1 + work.RETRY_SPREAD) for w in waits)


def test_backoff_spread_is_proportional_at_base_and_cap():
    from lib import lease

    short = [lease.backoff(0, base=30.0, cap=6 * 3600, spread=0.25) for _ in range(200)]
    long = [lease.backoff(20, base=30.0, cap=6 * 3600, spread=0.25) for _ in range(200)]
    assert (max(short) - min(short)) / 30.0 > 0.1
    assert (max(long) - min(long)) / 21600.0 > 0.1


def test_backoff_without_spread_doubles_per_attempt_with_absolute_jitter():
    from lib import lease

    assert [lease.backoff(n) for n in range(4)] == [1.0, 2.0, 4.0, 8.0]
    assert 1.0 <= lease.backoff(0, jitter=0.5) <= 1.5


def test_reclaim_sql_sets_randomized_exponential_next_attempt_at():
    from lib import work

    assert "next_attempt_at = now()," not in work.RECLAIM_SQL
    assert "make_interval" in work.RECLAIM_SQL
    assert "2 ^ lapses" in work.RECLAIM_SQL
    assert "random()" in work.RECLAIM_SQL


def test_reclaim_sql_placeholders_match_expected_param_names():
    from lib import work

    names = set(re.findall(r"%\((\w+)\)s", work.RECLAIM_SQL))
    assert names == {"kind", "max_lapses", "lapse_base", "lapse_cap"}


def test_revive_sql_resets_attempts_and_lapses():
    from lib import work

    assert "attempts = 0, lapses = 0" in work.REVIVE_SQL


def test_stale_after_hours_exceeds_nightly_budget_else_returns_default():
    from unittest import mock

    from lib import db

    with mock.patch.object(db.settings, "budget_minutes", return_value=720):
        assert db.stale_after_hours(object()) == 14
    with mock.patch.object(db.settings, "budget_minutes", return_value=60):
        assert db.stale_after_hours(object()) == db.STALE_AFTER_HOURS


def test_sweep_stale_runs_source_uses_stale_after_hours_when_max_age_is_none():
    import inspect

    from lib import db

    src = inspect.getsource(db.sweep_stale_runs)
    assert "if max_age_hours is None" in src
    assert "stale_after_hours(conn)" in src


def test_build_wait_seconds_reads_env_override_else_returns_default():
    import os
    from unittest import mock

    from lib import db

    with mock.patch.dict(os.environ, {"NEMO_BUILD_WAIT_SECONDS": "45"}):
        assert db.build_wait_seconds() == 45
    with mock.patch.dict(os.environ, {"NEMO_BUILD_WAIT_SECONDS": ""}):
        assert db.build_wait_seconds() == db.BUILD_WAIT_SECONDS
