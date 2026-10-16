import inspect

from ingest import dim_snapshot


def test_snapshot_sql_uses_observed_on_param_not_current_date():
    for sql in (dim_snapshot.MEMBER_SQL, dim_snapshot.CHANNEL_SQL):
        assert "current_date" not in sql, (
            "a nightly that crosses midnight would file the snapshot under the wrong day"
        )
        assert "%(observed_on)s" in sql


def test_run_reads_snapshot_day_from_logical_date_sql():
    assert "logical_date" in dim_snapshot.LOGICAL_DATE_SQL
    body = inspect.getsource(dim_snapshot.run)
    assert "LOGICAL_DATE_SQL" in body
    assert "counts.run_id" in body


def test_run_passes_same_observed_on_to_both_snapshots():
    body = inspect.getsource(dim_snapshot.run)
    assert body.count('{"observed_on": observed_on}') == 2
