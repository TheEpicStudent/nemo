import pathlib
import re

from lib import audit_actions

SQL = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0190_audit_view.sql").read_text()


def test_audit_view_migration_seeds_slim_actions_from_catalogue():
    seeded = re.findall(r"\(\d+, '([a-z_]+)'\)", SQL)
    assert sorted(seeded) == audit_actions.slim_actions()


def test_slim_actions_lists_four_high_volume_actions():
    assert audit_actions.slim_actions() == ["canvas_opened", "file_downloaded", "list_cell_updated",
                                            "public_channel_preview"]


def test_audit_view_table_has_only_filter_columns():
    table = SQL[SQL.index("CREATE TABLE slack.audit_view ("):SQL.index(") PARTITION BY RANGE (at);")]
    assert "payload" not in table and "context" not in table
    for column in ("id         uuid", "action     smallint", "actor_id", "object_id", "ip         inet",
                   "ua_id      integer", "session_id bigint"):
        assert column in table, column


def test_audit_view_migration_uses_ensure_months_for_both_tables():
    assert "slack.ensure_months('slack.audit_event_monthly', 'audit_event'" in SQL
    assert "SELECT slack.ensure_months('slack.audit_view', 'audit_view', '2025-11-01', 2);" in SQL
    assert "PARTITION OF slack.audit_view DEFAULT" in SQL


def test_audit_view_migration_indexes_action_at_id_only():
    assert "audit_view_recent_idx" not in SQL
    assert "ON slack.audit_view (action, at DESC, id DESC)" in SQL
