from jobs.nightly_sync import over_budget


def test_over_budget_without_budget_returns_none():
    assert over_budget(999, None, 5, "team_stats") is None
    assert over_budget(999, 0, 5, "team_stats") is None


def test_over_budget_with_no_completed_stage_returns_none():
    assert over_budget(999, 45, 0, "team_stats") is None
    assert over_budget(999, 45, 1, "team_stats") is not None


def test_over_budget_for_dbt_stage_returns_none():
    assert over_budget(999, 45, 5, "dbt") is None


def test_over_budget_below_limit_returns_none_and_at_limit_returns_reason():
    assert over_budget(44.9, 45, 5, "team_stats") is None
    assert over_budget(45, 45, 5, "team_stats") is not None


def test_over_budget_reason_includes_minutes_spent_and_limit():
    assert "46 of 45 minutes" in over_budget(45.6, 45, 5, "member_days")
