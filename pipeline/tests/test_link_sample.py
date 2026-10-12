import pathlib

MIGRATION = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0216_link_sample_and_shadow.sql").read_text()


def test_a_shadow_link_carries_every_live_column_under_its_variant():
    for column in ("score", "top_signal", "top_family", "families", "signals", "label", "first_seen", "last_seen"):
        assert f"    {column} " in MIGRATION
    assert "PRIMARY KEY (variant, a_user_id, b_user_id)" in MIGRATION
    assert "CHECK (a_user_id < b_user_id)" in MIGRATION


def test_a_link_is_sampled_once_per_variant_with_its_band():
    assert "CONSTRAINT link_sample_pair_key UNIQUE (variant, a_user_id, b_user_id)" in MIGRATION
    assert "CHECK (band IN ('certain', 'strong', 'weak'))" in MIGRATION
    assert "variant    text         NOT NULL DEFAULT 'live'" in MIGRATION


def test_the_pipeline_writes_samples_and_fire_engine_only_reads_them():
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON fd.member_link_shadow, fd.link_sample TO pipeline_writer" in MIGRATION
    assert "GRANT SELECT ON fd.member_link_shadow, fd.link_sample TO rails_app" in MIGRATION
