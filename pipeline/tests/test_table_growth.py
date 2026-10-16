from checks import table_growth

MB = 1024 * 1024


def test_flagged_above_twice_median_returns_true():
    assert table_growth.flagged(500 * MB, 200 * MB, 30)
    assert not table_growth.flagged(390 * MB, 200 * MB, 30)


def test_flagged_small_table_uses_floor_as_limit():
    assert not table_growth.flagged(90 * MB, 1 * MB, 30)
    assert table_growth.flagged(120 * MB, 1 * MB, 30)
    assert table_growth.limit(None) == table_growth.FLOOR_BYTES


def test_flagged_below_fewest_days_returns_false():
    assert not table_growth.flagged(900 * MB, 1 * MB, table_growth.FEWEST_DAYS - 1)
    assert table_growth.flagged(900 * MB, 1 * MB, table_growth.FEWEST_DAYS)


def test_flagged_with_negative_or_none_growth_returns_false():
    assert not table_growth.flagged(-900 * MB, 10 * MB, 30)
    assert not table_growth.flagged(None, 10 * MB, 30)


def test_results_with_flagged_table_returns_error_row_and_warn_summary():
    growth_rows = [(500 * MB, 100 * MB, True, "slack.audit_event"), (1 * MB, 1 * MB, False, "fd.member")]

    results = table_growth.results(growth_rows)

    assert results[0] == ("slack.audit_event grows under twice its 30-day median", "error", "fail",
                          "grew 500 MB in a day", "under 200 MB")
    assert results[-1][1:4] == ("info", "warn", "1 of 2 table(s) flagged")
    assert len(results) == 2


def test_results_without_flagged_tables_returns_single_pass_summary():
    assert table_growth.results([(1 * MB, 1 * MB, False, "fd.member")]) == [
        ("no table grows past twice its 30-day median", "info", "pass", "0 of 1 table(s) flagged", "0 flagged")]


def test_growth_sql_divides_by_day_gap():
    assert "/ nullif(day - lag(day) OVER per_table, 0)" in table_growth.GROWTH_SQL


def test_snapshot_sql_sums_partitions_and_excludes_partition_children():
    sql = table_growth.SNAPSHOT_SQL
    assert "pg_partition_tree(c.oid) WHERE c.relkind = 'p'" in sql
    assert "NOT c.relispartition" in sql
