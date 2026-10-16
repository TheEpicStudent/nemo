import contextlib
import pytest
import json

from jobs.nightly_sync import credential_faults, parent_status, retryable, dbt_outcomes
from lib.db import SyncCancelled
from lib.proxy_client import (
    InternalApiError,
    InternalAuthError,
    ProxyError,
    ProxyUnavailableError,
)


def test_retryable_internal_auth_error_returns_false():
    assert retryable(InternalAuthError("invalid_auth")) is False


def test_retryable_sync_cancelled_returns_false():
    assert retryable(SyncCancelled("cancel requested")) is False


def test_retryable_proxy_allowlist_rejection_returns_false():
    assert retryable(ProxyError("method not in the allowlist")) is False


def test_retryable_proxy_unavailable_error_returns_true():
    exc = ProxyUnavailableError("connection refused")
    assert isinstance(exc, ProxyError)
    assert retryable(exc) is True


def test_retryable_internal_api_error_returns_true():
    assert retryable(InternalApiError("ratelimited")) is True


def test_retryable_runtime_and_key_errors_return_true():
    assert retryable(RuntimeError("boom")) is True
    assert retryable(KeyError("user_id")) is True


def test_retryable_proxy_gateway_status_returns_true():
    assert retryable(ProxyError("proxy returned 502: ")) is True
    assert retryable(ProxyError("proxy returned 503: ")) is True
    assert retryable(ProxyError("proxy returned 504: ")) is True


def test_retryable_proxy_refusal_status_returns_false():
    assert retryable(ProxyError("proxy returned 401: invalid bearer token")) is False
    assert retryable(ProxyError("proxy returned 403: method not allowed")) is False
    assert retryable(ProxyError("proxy returned 400: unknown credential")) is False
    assert retryable(ProxyError("proxy returned 500: ")) is False


def test_retryable_walk_integrity_error_returns_false():
    assert retryable(ProxyError("search.messages: page repeated after 1500 records")) is False


def test_credential_faults_failed_credential_returns_error_text():
    report = {"ok": False, "credentials": {
        "internal": {"ok": False, "error": "invalid_auth"},
        "admin": {"ok": True, "user": "epsmnemosyne"},
    }}
    assert credential_faults(report) == ["internal: invalid_auth"]


def test_credential_faults_both_credentials_ok_returns_empty():
    report = {"ok": True, "credentials": {
        "internal": {"ok": True, "user": "dracula"},
        "admin": {"ok": True, "user": "epsmnemosyne"},
    }}
    assert credential_faults(report) == []


def test_credential_faults_failed_credential_without_error_returns_not_ok():
    assert credential_faults({"credentials": {"admin": {"ok": False}}}) == ["admin: not ok"]


def test_parent_status_maps_counts_to_status():
    ok = []
    fails = [("a", "x")]
    assert parent_status(True, 5, 0, 0, ok) == "cancelled"
    assert parent_status(False, 0, 0, 0, ok) == "failed"
    assert parent_status(False, 0, 20, 0, ok) == "ok"
    assert parent_status(False, 20, 0, 0, ok) == "ok"
    assert parent_status(False, 20, 0, 0, fails) == "partial"
    assert parent_status(False, 1, 0, 0, fails) == "failed"
    assert parent_status(False, 20, 0, 3, ok) == "partial"
    assert parent_status(False, 19, 0, 1, fails * 19) == "failed"
    assert parent_status(False, 20, 5, 1, fails) == "partial"
    assert parent_status(True, 0, 0, 0, ok) == "cancelled"


def test_dbt_outcomes_separates_fail_and_error_from_warn():
    results = {"results": [
        {"unique_id": "test.mnemosyne.not_null_dim_member_user_id", "status": "pass"},
        {"unique_id": "test.mnemosyne.assert_cohort_dates_are_not_stamped", "status": "warn"},
        {"unique_id": "test.mnemosyne.unique_mart_growth_month", "status": "fail"},
        {"unique_id": "test.mnemosyne.assert_member_dates_are_plausible", "status": "error"},
        {"unique_id": "model.mnemosyne.mart_growth", "status": "success"},
    ]}
    failed, warned = dbt_outcomes(results)
    assert failed == [("unique_mart_growth_month", "fail"), ("assert_member_dates_are_plausible", "error")]
    assert warned == [("assert_cohort_dates_are_not_stamped", "warn")]
    assert dbt_outcomes({}) == ([], [])


def test_credential_faults_reply_without_credentials_returns_proxy_fault():
    assert credential_faults({"detail": "invalid bearer token"}) == ["proxy: invalid bearer token"]
    assert credential_faults({}) == ["proxy: no credential report"]


def test_run_dbt_gate_test_failure_raises_runtime_error(monkeypatch, tmp_path):
    from jobs import nightly_sync

    results = tmp_path / "run_results.json"
    results.write_text(json.dumps({"results": [
        {"unique_id": "test.mnemosyne.assert_claimed_counts_track_slack", "status": "fail"},
    ]}))
    monkeypatch.setattr(nightly_sync, "RUN_RESULTS", results)
    monkeypatch.setattr(nightly_sync, "ensure_dbt_profile", lambda: None)
    monkeypatch.setattr(nightly_sync, "check_freshness", lambda counts=None: 0)
    monkeypatch.setattr(nightly_sync, "dbt", lambda *a: 0)
    monkeypatch.setattr(nightly_sync, "build_lock",
                        lambda **kw: contextlib.nullcontext())

    with pytest.raises(RuntimeError, match="gate test\\(s\\) failed"):
        nightly_sync.run_dbt()


def test_run_dbt_ungated_test_failure_does_not_raise(monkeypatch, tmp_path):
    from jobs import nightly_sync

    results = tmp_path / "run_results.json"
    results.write_text(json.dumps({"results": [
        {"unique_id": "test.mnemosyne.not_null_fct_message_ts", "status": "fail"},
    ]}))
    monkeypatch.setattr(nightly_sync, "RUN_RESULTS", results)
    monkeypatch.setattr(nightly_sync, "ensure_dbt_profile", lambda: None)
    monkeypatch.setattr(nightly_sync, "check_freshness", lambda counts=None: 0)
    monkeypatch.setattr(nightly_sync, "dbt", lambda *a: 0)
    monkeypatch.setattr(nightly_sync, "build_lock",
                        lambda **kw: contextlib.nullcontext())

    nightly_sync.run_dbt()


def test_gate_tests_all_exist_as_singular_test_files():
    from pathlib import Path

    from jobs.nightly_sync import GATE_TESTS
    from lib.paths import WAREHOUSE_DIR

    on_disk = {p.stem for p in Path(WAREHOUSE_DIR, "tests").glob("*.sql")}
    assert set(GATE_TESTS) <= on_disk, set(GATE_TESTS) - on_disk


def test_gate_tests_have_no_warn_severity():
    from pathlib import Path

    from jobs.nightly_sync import GATE_TESTS
    from lib.paths import WAREHOUSE_DIR

    warned = [
        name for name in GATE_TESTS
        if "severity='warn'" in Path(WAREHOUSE_DIR, "tests", f"{name}.sql").read_text()
    ]
    assert not warned, (
        "dbt_outcomes files a warn under `warned`, and `gated` only reads `failed`, so a "
        f"gate test carrying severity='warn' can never gate: {warned}"
    )


def test_parent_fault_ok_or_partial_without_failures_returns_none():
    from jobs.nightly_sync import parent_fault

    assert parent_fault("ok", False, []) == (None, None)
    assert parent_fault("partial", False, []) == (None, None)


def test_parent_fault_partial_with_failed_stage_names_stage():
    from jobs.nightly_sync import parent_fault

    klass, detail = parent_fault("partial", False, [("prometheans", "boom")])
    assert klass == "local"
    assert "prometheans" in detail


def test_parent_fault_terminal_statuses_return_class_and_detail():
    from jobs.nightly_sync import parent_fault, parent_status

    for cancelled, completed, skipped, cut, failed in [
        (True, 0, 0, 0, []),
        (False, 0, 0, 0, []),
        (False, 2, 0, 0, [("a", "x"), ("b", "y")]),
    ]:
        status = parent_status(cancelled, completed, skipped, cut, failed)
        klass, detail = parent_fault(status, cancelled, failed)
        assert klass is not None, status
        assert detail


def test_record_quality_runs_every_check_module():
    import inspect
    from pathlib import Path

    from jobs import nightly_sync

    modules = {p.stem for p in (Path(__file__).parent.parent / "checks").glob("*.py")
               if p.stem != "__init__"}
    src = inspect.getsource(nightly_sync.record_quality)
    missing = [m for m in sorted(modules) if f'("{m}"' not in src]
    assert missing == [], f"check modules written but never run: {missing}"


def test_record_quality_catches_check_exceptions_and_rolls_back():
    import inspect

    from jobs import nightly_sync

    src = inspect.getsource(nightly_sync.record_quality)
    assert "except Exception" in src
    assert "conn.rollback()" in src


def test_run_stage_lock_timeout_reaps_orphaned_dbt():
    import inspect

    from jobs import nightly_sync

    src = inspect.getsource(nightly_sync.run_stage)
    assert "LOCK_TIMEOUT.search" in src
    assert "reap_orphaned_dbt(began)" in src


def test_orphaned_dbt_sql_targets_own_stale_dbt_backends():
    from jobs import nightly_sync

    sql = nightly_sync.ORPHANED_DBT_SQL
    assert "usename = current_user" in sql
    assert 'query LIKE \'%%"app": "dbt"%%\'' in sql, (
        "psycopg reads a single %% as a placeholder, so the LIKE pattern has to double them "
        "or every reap dies with ProgrammingError before it terminates anything"
    )
    assert "pid <> pg_backend_pid()" in sql
    assert "query_start < now() - make_interval" in sql


def test_reap_orphaned_dbt_connect_failure_returns_zero():
    from datetime import datetime, timezone
    from unittest import mock

    from jobs import nightly_sync

    with mock.patch.object(nightly_sync, "connect", side_effect=RuntimeError("nope")):
        assert nightly_sync.reap_orphaned_dbt(datetime.now(timezone.utc)) == 0


def test_sync_worker_source_excludes_run_dbt():
    import inspect

    from jobs import nightly_sync, sync_worker

    assert "run_dbt" not in inspect.getsource(sync_worker), (
        "community analytics may be a day old, and what Fire Engine reads from dbt is a view "
        "or comes from the nightly pull, so a build between nights rewrites tables nobody waits on"
    )
    assert nightly_sync.stages()[-1][0] == nightly_sync.TRANSFORM


def test_run_dbt_takes_build_lock():
    import inspect

    from jobs import nightly_sync

    src = inspect.getsource(nightly_sync.run_dbt)
    assert "with build_lock(wait_seconds=wait_seconds):" in src, (
        "the nightly and the transform CLI both reach dbt through run_dbt, so the lock "
        "belongs here or a hand-run build still races the scheduler"
    )


def test_orphaned_dbt_sql_filters_backends_started_before_attempt():
    from jobs import nightly_sync

    sql = nightly_sync.ORPHANED_DBT_SQL
    assert "backend_start < %s" in sql, (
        "without a floor the reaper kills any dbt backend older than two minutes, including "
        "the long build it was called to protect"
    )


def test_reap_orphaned_dbt_before_parameter_has_no_default():
    import inspect

    from jobs import nightly_sync

    floor = inspect.signature(nightly_sync.reap_orphaned_dbt).parameters["before"]
    assert floor.default is inspect.Parameter.empty
