from checks import metrics
from lib import sources


def test_nightly_keys_count_matches_stages_and_is_below_keys():
    from jobs import nightly_sync

    assert len(sources.NIGHTLY_KEYS) == len(nightly_sync.stages())
    assert len(sources.NIGHTLY_KEYS) < len(sources.KEYS)


def test_bound_verdict_at_least_above_bound_returns_ok_state():
    state, _ = metrics.bound_verdict("longest unbroken run of member-days", 1100, 15)
    assert state == "ok"


def test_bound_verdict_at_least_below_bound_returns_differs_state():
    state, _ = metrics.bound_verdict("longest unbroken run of member-days", 9, 15)
    assert state == "differs"


def test_bound_verdict_at_most_zero_returns_ok_state():
    state, _ = metrics.bound_verdict("channel daily pull, days behind the walk", 0, 2)
    assert state == "ok"


def test_bound_verdict_at_most_above_bound_returns_differs_state():
    state, _ = metrics.bound_verdict("channel daily pull, days behind the walk", 5, 2)
    assert state == "differs"


def test_bound_verdict_missing_reading_returns_no_data():
    assert metrics.bound_verdict("longest unbroken run of member-days", None, 15)[0] == "no data"


def test_bounds_excludes_first_post_coverage_checks():
    for name in (
        "first-post dates with a day-30 observation",
        "first-post dates with a day-90 observation",
        "first-post dates where visits are knowable",
    ):
        assert name not in metrics.BOUNDS


def test_bounds_values_are_at_least_or_at_most():
    assert set(metrics.BOUNDS.values()) <= {metrics.AT_LEAST, metrics.AT_MOST}


def test_status_of_covers_every_bound_state():
    for state in ("ok", "differs", "no data"):
        assert state in metrics.STATUS_OF
