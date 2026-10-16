import pathlib

SQL = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0189_audit_event_monthly.sql").read_text()


def test_audit_event_monthly_partitions_by_range_with_composite_key():
    assert "PARTITION BY RANGE (at)" in SQL
    assert "PRIMARY KEY (id, at)" in SQL
    assert "id           uuid" in SQL


def test_audit_event_monthly_defines_typed_search_columns():
    for column in ("category", "actor_email", "entity_email", "channel_id", "ip           inet",
                   "ua_id        integer", "session_id   bigint"):
        assert column in SQL, column
    assert "context" not in SQL
    assert "tsvector" not in SQL


def test_audit_event_monthly_sets_lz4_compression_on_each_partition():
    assert SQL.count("SET COMPRESSION lz4") == 3
    assert "toast_tuple_target" not in SQL


def test_audit_event_monthly_references_deduplicated_user_agent_table():
    assert "REFERENCES slack.user_agent (id)" in SQL
    assert "ON slack.user_agent (md5(ua))" in SQL


def test_audit_event_monthly_has_default_partition_and_ahead_months():
    assert "PARTITION OF slack.audit_event_monthly DEFAULT" in SQL
    assert "SELECT slack.ensure_audit_event_months('2025-11-01', 2);" in SQL
    assert "00:00:00+00" in SQL
