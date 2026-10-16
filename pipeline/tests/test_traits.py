import pathlib
import re

from lib import traits

MIGRATIONS = pathlib.Path(__file__).parents[2] / "db" / "migrations"
MIGRATION = MIGRATIONS / "0196_member_trait.sql"
IDENTITY = MIGRATIONS / "0197_member_trait_identity.sql"
LOGINS = MIGRATIONS / "0198_member_trait_logins.sql"


def test_member_trait_kind_check_matches_traits_kinds():
    sql = IDENTITY.read_text()
    listed = re.search(r"kind IN \((.*?)\)\)", sql, re.S).group(1)
    assert tuple(re.findall(r"'([a-z_0-9]+)'", listed)) == traits.KINDS


def test_member_trait_migration_indexes_kind_and_value():
    assert "ON fd.member_trait (kind, value)" in MIGRATION.read_text()


def test_member_trait_migration_primary_key_is_user_kind_value():
    assert "PRIMARY KEY (user_id, kind, value)" in MIGRATION.read_text()


def test_member_trait_identity_migration_has_insert_update_delete_triggers():
    sql = IDENTITY.read_text()
    for table, columns in (("fd.member_identity", "email, real_name"), ("fd.member", "display_name, handle")):
        assert f"AFTER INSERT ON {table}" in sql
        assert f"AFTER UPDATE OF {columns} ON {table}" in sql
        assert f"AFTER DELETE ON {table}" in sql


def test_member_trait_audit_trigger_fires_for_anomaly_and_user_created_only():
    assert "WHEN (NEW.action IN ('anomaly', 'user_created'))" in IDENTITY.read_text()


def test_member_trait_logins_migration_adds_hits_delta_to_seen():
    sql = LOGINS.read_text()
    assert "NEW.hits - CASE WHEN TG_OP = 'UPDATE' THEN OLD.hits ELSE 0 END" in sql
    assert "seen = held.seen + EXCLUDED.seen" in sql


def test_member_trait_logins_backfill_groups_by_ip_and_prefix():
    sql = LOGINS.read_text()
    assert "GROUP BY user_id, host(ip)" in sql and "GROUP BY user_id, host(ip_prefix)" in sql
