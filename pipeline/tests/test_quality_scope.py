import inspect

from jobs import invariants, nightly_sync, reconcile


def test_i11_day_sources_recent_filters_source_by_day_ledgers():
    body = inspect.getsource(invariants.i11_day_sources_recent)
    assert "DAY_LEDGERS" in body
    assert "source = ANY(%s)" in body


def test_day_ledgers_excludes_member_day_import():
    day_sources = [day_source for day_source, _ in invariants.DAY_LEDGERS]
    assert "member_day_import" not in day_sources


def test_dead_sql_uses_stuck_after_hours_twice_revive_hours_and_null_next_attempt():
    from lib import work

    assert reconcile.STUCK_AFTER_HOURS == 2 * work.REVIVE_HOURS
    assert "next_attempt_at IS NULL" in reconcile.DEAD_SQL
    assert f"make_interval(hours => {reconcile.STUCK_AFTER_HOURS})" in reconcile.DEAD_SQL


def test_dead_sql_excludes_entity_prefix_and_refusals():
    assert "<> 'entity:'" in reconcile.DEAD_SQL
    assert "<> ALL(%s::text[])" in reconcile.DEAD_SQL


def test_r6_dead_units_uses_work_refusals():
    from lib import work

    body = inspect.getsource(reconcile.r6_dead_units)
    assert "work.REFUSALS" in body
    assert "channel_not_found" in work.REFUSALS


def test_reconcile_prometheans_opens_ingest_run_and_counts_rows_in():
    body = inspect.getsource(nightly_sync.reconcile_prometheans)
    assert "ingest_run(conn, PROMETHEANS)" in body
    assert "counts.rows_in" in body


def test_stages_includes_prometheans_stage():
    entries = {name: stage for name, stage in nightly_sync.stages()}
    assert nightly_sync.PROMETHEANS in entries
