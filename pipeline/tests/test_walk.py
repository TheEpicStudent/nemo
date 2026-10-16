import pathlib
from datetime import date

import pytest

from lib import lease
from lib.walk import (
    COMPLETE,
    NO_FLOOR,
    SHORT,
    UNVERIFIED,
    WalkMismatchError,
    check_walk,
    supersedes,
    should_prune,
    window_totals,
)


def test_check_walk_full_count_returns_complete_and_prunes():
    assert check_walk("x", 216_540, 216_540, 500) == COMPLETE
    assert check_walk("x", 216_100, 216_540, 500) == COMPLETE
    assert should_prune(COMPLETE)


def test_check_walk_short_count_returns_short_and_does_not_prune(capsys):
    assert check_walk("member range", 150_000, 216_540, 500) == SHORT
    assert "short" in capsys.readouterr().out
    assert not should_prune(SHORT)
    assert not should_prune(None)


def test_check_walk_over_num_found_raises_walk_mismatch_error():
    with pytest.raises(WalkMismatchError):
        check_walk("x", 1_200, 500, 500)
    assert check_walk("x", 10, None, 500) is None


def test_backoff_doubles_per_attempt_and_caps_at_sixty_seconds():
    assert [lease.backoff(n) for n in range(4)] == [1.0, 2.0, 4.0, 8.0]
    assert lease.backoff(20) == 60.0
    assert 1.0 <= lease.backoff(0, jitter=0.5) <= 1.5


def test_backoff_large_attempt_count_returns_cap():
    assert lease.backoff(5168, base=30.0, cap=6 * 3600) == 6 * 3600
    assert lease.backoff(10**6, base=30.0, cap=60.0) == 60.0


def test_check_walk_short_at_zero_or_negative_raises_value_error():
    with pytest.raises(ValueError, match="no floor"):
        check_walk("member analytics", 1, 216_540, 500, short_at=0)
    with pytest.raises(ValueError, match="no floor"):
        check_walk("member analytics", 1, 216_540, 500, short_at=-0.1)


def test_check_walk_no_floor_returns_unverified_and_does_not_prune():
    assert check_walk("member analytics", 61_940, 100_000, 500, short_at=NO_FLOOR) == UNVERIFIED
    assert not should_prune(UNVERIFIED)
    with pytest.raises(WalkMismatchError):
        check_walk("member analytics", 101_000, 100_000, 500, short_at=NO_FLOOR)


def test_member_short_at_is_no_floor_and_check_walk_returns_unverified():
    from ingest.analytics_pull import MEMBER_SHORT_AT

    assert MEMBER_SHORT_AT is NO_FLOOR
    assert check_walk("member analytics", 75_660, 100_000, 500,
                      short_at=MEMBER_SHORT_AT) == UNVERIFIED


def test_check_walk_unverified_verdict_is_distinct_from_complete_and_short():
    from lib import walk

    assert walk.UNVERIFIED not in (walk.COMPLETE, walk.SHORT)
    assert check_walk("x", 216_100, 216_540, 500) == COMPLETE
    assert check_walk("x", 100, 216_540, 500) == SHORT
    assert check_walk("x", 100, 216_540, 500, short_at=NO_FLOOR) == UNVERIFIED


def test_walk_verdicts_are_allowed_by_slice_coverage_check_constraint():
    import re

    from lib import walk
    from lib.paths import MIGRATIONS_DIR

    sql = (MIGRATIONS_DIR / "0093_slice_coverage_unverified.sql").read_text()
    allowed = set(re.findall(r"'(\w+)'", sql.split("CHECK")[1].split(")")[0]))
    for verdict in (walk.COMPLETE, walk.SHORT, walk.UNVERIFIED):
        assert verdict in allowed


NEW = (date(2026, 3, 1), date(2026, 3, 30))
OLD = (date(2026, 2, 1), date(2026, 2, 28))
OLDER = (date(2026, 1, 1), date(2026, 1, 31))


def test_supersedes_window_matching_prior_rows_returns_true():
    window_rows, other_max_rows = window_totals([(*NEW, 40_000), (*OLD, 39_900)], NEW)
    assert (window_rows, other_max_rows) == (40_000, 39_900)
    assert supersedes(window_rows, other_max_rows)


def test_supersedes_collapsed_window_returns_false():
    window_rows, other_max_rows = window_totals([(*NEW, 1_200), (*OLD, 40_000)], NEW)
    assert not supersedes(window_rows, other_max_rows)


def test_supersedes_small_drop_returns_true_and_large_drop_returns_false():
    assert supersedes(39_000, 40_000)
    assert not supersedes(35_000, 40_000)


def test_window_totals_uses_largest_other_window_as_comparison():
    window_rows, other_max_rows = window_totals([(*NEW, 30_000), (*OLD, 12_000), (*OLDER, 40_000)], NEW)
    assert other_max_rows == 40_000
    assert not supersedes(window_rows, other_max_rows)


def test_window_totals_first_window_has_zero_other_max_and_supersedes():
    window_rows, other_max_rows = window_totals([(*NEW, 12)], NEW)
    assert (window_rows, other_max_rows) == (12, 0)
    assert supersedes(window_rows, other_max_rows)


def test_channel_range_pull_source_keeps_cursor_for_non_replacing_window():
    source = pathlib.Path("ingest/channel_range_pull.py").read_text()

    assert 'walked = {"cursor": resume_at}' in source
    assert 'walked["cursor"] = cursor' in source
    assert 'None if replacing else walked["cursor"]' in source, (
        "a window that did not replace the fuller one must keep its cursor"
    )
