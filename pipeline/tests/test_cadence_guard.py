import inspect
from datetime import datetime, timedelta, timezone

from jobs import nightly_sync
from lib import settings


def stub_settings(monkeypatch, last_ok, cadence="daily", enabled=True):
    monkeypatch.setattr(settings, "enabled", lambda conn, key: enabled)
    monkeypatch.setattr(settings, "cadence", lambda conn, key: cadence)
    monkeypatch.setattr(settings, "last_ok", lambda conn, key: last_ok)


def test_skip_reason_before_stage_time_returns_reason_and_at_stage_time_returns_none(monkeypatch):
    last_ok = datetime(2026, 9, 15, 7, 7, tzinfo=timezone.utc)
    stub_settings(monkeypatch, last_ok)

    at_plan_time = datetime(2026, 9, 16, 3, 0, tzinfo=timezone.utc)
    at_stage_time = datetime(2026, 9, 16, 7, 0, tzinfo=timezone.utc)

    assert settings.skip_reason(None, "dim_snapshot", at_plan_time) is not None
    assert settings.skip_reason(None, "dim_snapshot", at_stage_time) is None


def test_todays_run_defers_cadence_check_with_when_due(monkeypatch):
    monkeypatch.setattr(nightly_sync, "stages", lambda: [("dim_snapshot", lambda conn: None)])
    plan = nightly_sync.todays_run(None)
    assert [reason for _, _, reason in plan] == [nightly_sync.WHEN_DUE]


def test_stage_plan_named_stage_has_none_reason():
    plan = nightly_sync.stage_plan("team_stats")
    assert plan[0][2] is None
    assert plan[0][2] is not nightly_sync.WHEN_DUE


def test_run_stages_resolves_when_due_before_transform_skip_reason():
    body = inspect.getsource(nightly_sync.run_stages)
    assert "if why is WHEN_DUE:" in body
    assert body.index("if why is WHEN_DUE:") < body.index("transform_skip_reason(")


def test_period_daily_is_twenty_hours():
    assert settings.PERIOD["daily"] == timedelta(hours=20)
