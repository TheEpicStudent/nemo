import pathlib

MIGRATION = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0216_link_sample_and_shadow.sql").read_text()


def test_link_sample_migration_shadow_table_has_live_columns_and_variant_key():
    for column in ("score", "top_signal", "top_family", "families", "signals", "label", "first_seen", "last_seen"):
        assert f"    {column} " in MIGRATION
    assert "PRIMARY KEY (variant, a_user_id, b_user_id)" in MIGRATION
    assert "CHECK (a_user_id < b_user_id)" in MIGRATION


def test_link_sample_migration_sample_table_has_unique_variant_pair_and_band_check():
    assert "CONSTRAINT link_sample_pair_key UNIQUE (variant, a_user_id, b_user_id)" in MIGRATION
    assert "CHECK (band IN ('certain', 'strong', 'weak'))" in MIGRATION
    assert "variant    text         NOT NULL DEFAULT 'live'" in MIGRATION


def test_link_sample_migration_grants_write_to_pipeline_writer_and_select_to_rails_app():
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON fd.member_link_shadow, fd.link_sample TO pipeline_writer" in MIGRATION
    assert "GRANT SELECT ON fd.member_link_shadow, fd.link_sample TO rails_app" in MIGRATION
