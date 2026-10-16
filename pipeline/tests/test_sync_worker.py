from datetime import datetime, timedelta

import pytest

from jobs.nightly_sync import stage_plan
from jobs.sync_worker import missed_today, next_run_at, slot_today, wait_seconds


def test_next_run_at_time_after_now_returns_today():
    now = datetime(2026, 8, 4, 1, 30)
    assert next_run_at("03:00", now) == datetime(2026, 8, 4, 3, 0)


def test_next_run_at_time_before_now_returns_tomorrow():
    now = datetime(2026, 8, 4, 5, 30)
    assert next_run_at("03:00", now) == datetime(2026, 8, 5, 3, 0)


def test_next_run_at_exact_slot_minute_returns_tomorrow():
    now = datetime(2026, 8, 4, 3, 0)
    assert next_run_at("03:00", now) == datetime(2026, 8, 5, 3, 0)


def test_next_run_at_month_end_rolls_to_next_month():
    now = datetime(2026, 8, 31, 23, 59)
    assert next_run_at("03:00", now) == datetime(2026, 9, 1, 3, 0)


def test_next_run_at_drops_seconds_and_microseconds():
    now = datetime(2026, 8, 4, 2, 59, 59, 999999)
    assert next_run_at("03:00", now) == datetime(2026, 8, 4, 3, 0, 0, 0)


def test_wait_seconds_near_scheduled_run_returns_remaining_seconds():
    now = datetime(2026, 8, 4, 2, 59, 50)
    scheduled = datetime(2026, 8, 4, 3, 0)
    assert wait_seconds(60, scheduled, now) == 10.0


def test_wait_seconds_far_scheduled_run_returns_poll_interval():
    now = datetime(2026, 8, 4, 12, 0)
    scheduled = datetime(2026, 8, 5, 3, 0)
    assert wait_seconds(60, scheduled, now) == 60.0


def test_wait_seconds_at_scheduled_time_returns_one_second():
    now = datetime(2026, 8, 4, 3, 0)
    scheduled = datetime(2026, 8, 4, 3, 0)
    assert wait_seconds(60, scheduled, now) == 1.0


def test_missed_today_after_slot_without_run_returns_true():
    now = datetime(2026, 9, 20, 9, 51)
    assert missed_today("03:00", now, already_ran=False)


def test_missed_today_after_slot_already_ran_returns_false():
    now = datetime(2026, 9, 20, 9, 51)
    assert not missed_today("03:00", now, already_ran=True)


def test_missed_today_before_slot_returns_false():
    now = datetime(2026, 9, 20, 2, 36)
    assert not missed_today("03:00", now, already_ran=False)


def test_missed_today_at_slot_minute_returns_true():
    now = datetime(2026, 9, 20, 3, 0)
    assert missed_today("03:00", now, already_ran=False)


def test_slot_today_and_next_run_at_agree_on_slot_time():
    now = datetime(2026, 9, 20, 9, 51)
    assert slot_today("03:00", now) == datetime(2026, 9, 20, 3, 0)
    assert next_run_at("03:00", now) == slot_today("03:00", now) + timedelta(days=1)


def test_boot_run_returns_startup_catch_up_or_none(monkeypatch):
    from jobs import sync_worker

    now = datetime(2026, 9, 20, 9, 51)
    monkeypatch.setattr(sync_worker, "run_at_start_enabled", lambda: True)
    assert sync_worker.boot_run("03:00", now, True, 0) == "startup"
    monkeypatch.setattr(sync_worker, "run_at_start_enabled", lambda: False)
    assert sync_worker.boot_run("03:00", now, True, 0) is None
    assert sync_worker.boot_run("03:00", now, False, 0) == "catch-up"


def test_boot_run_at_max_catch_ups_with_startup_flag_returns_none(monkeypatch):
    from jobs import sync_worker

    monkeypatch.setattr(sync_worker, "run_at_start_enabled", lambda: True)
    assert sync_worker.boot_run(
        "03:00", datetime(2026, 9, 20, 9, 51), False, sync_worker.MAX_CATCH_UPS
    ) is None


def test_missed_today_ledger_fallback_status_returns_false():
    from jobs import sync_worker

    assert not sync_worker.missed_today(
        "03:00", datetime(2026, 9, 20, 9, 51), *(True, sync_worker.MAX_CATCH_UPS)
    )


def test_ran_today_sql_excludes_abandoned_from_completed_count():
    from jobs import sync_worker

    assert "FILTER (WHERE status IS DISTINCT FROM 'abandoned')" in sync_worker.RAN_TODAY_SQL


def test_missed_today_abandoned_below_cap_returns_true_at_cap_returns_false():
    from jobs import sync_worker

    now = datetime(2026, 9, 20, 9, 51)
    assert sync_worker.missed_today("03:00", now, False, abandoned=0)
    assert not sync_worker.missed_today("03:00", now, False, abandoned=sync_worker.MAX_CATCH_UPS)


def test_ran_today_sql_counts_only_abandoned_toward_cap():
    from jobs import sync_worker

    assert "FILTER (WHERE status = 'abandoned')" in sync_worker.RAN_TODAY_SQL, (
        "a clean deploy must not burn a catch-up; only a abandoned night should"
    )


def test_ran_today_sql_does_not_filter_cancelled_status():
    from jobs import sync_worker

    assert "'abandoned'" in sync_worker.RAN_TODAY_SQL
    assert "cancelled" not in sync_worker.RAN_TODAY_SQL


def test_ran_today_sql_and_start_run_sql_use_current_date():
    from jobs import sync_worker
    from lib import db

    assert "logical_date = current_date" in sync_worker.RAN_TODAY_SQL
    assert "current_date" in db.START_RUN_SQL


def test_stage_plan_named_stage_returns_single_entry():
    plan = stage_plan("team_stats")
    assert len(plan) == 1
    assert plan[0][0] == "team_stats"


def test_stage_plan_unknown_stage_raises_value_error():
    with pytest.raises(ValueError):
        stage_plan("not_a_stage")


def test_sync_worker_main_calls_clear_stale_sessions():
    import inspect

    from jobs import sync_worker

    assert "clear_stale_sessions" in inspect.getsource(sync_worker.main)


def test_sync_and_archive_workers_call_clear_stale_sessions():
    import inspect

    from jobs import archive_worker, sync_worker

    for mod, fn in ((sync_worker, sync_worker.main), (archive_worker, archive_worker.serve)):
        assert "clear_stale_sessions" in inspect.getsource(fn), mod.__name__


def test_sync_worker_main_expires_stale_runs_with_zero_hours_at_startup():
    import inspect

    from jobs import sync_worker

    main = inspect.getsource(sync_worker.main)
    assert "expire_stale_runs(stale_after_hours=0)" in main, (
        "at startup every claimed request is stranded, because the worker holding it is gone"
    )


def test_sync_worker_loop_calls_expire_stale_runs_with_default_hours():
    import inspect

    from jobs import sync_worker

    body = inspect.getsource(sync_worker)
    loop = body.split("def main(")[1]
    assert loop.count("expire_stale_runs()") >= 2, "the in-loop reaps must stay time-based"


def test_release_stale_sql_includes_claimed_and_cancelling_status():
    from jobs import sync_worker

    assert "status IN ('claimed', 'cancelling')" in sync_worker.RELEASE_STALE_SQL
