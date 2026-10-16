import yaml

from lib.paths import MIGRATIONS_DIR, WAREHOUSE_DIR

SCHEMA = WAREHOUSE_DIR / "models" / "staging" / "schema.yml"
CONTRACTED = ("fct_message", "fct_member_message", "fct_message_first_post")


def models():
    return {m["name"]: m for m in yaml.safe_load(SCHEMA.read_text())["models"]}


def shape(model):
    return [(c["name"], c.get("data_type")) for c in model.get("columns", [])]


def test_staging_schema_enforces_contract_on_archive_models():
    model_specs = models()
    for name in CONTRACTED:
        enforced = model_specs[name].get("config", {}).get("contract", {}).get("enforced")
        assert enforced is True, f"{name} has no enforced contract"


def test_staging_schema_contracted_columns_declare_data_type():
    model_specs = models()
    for name in CONTRACTED:
        missing = [col for col, kind in shape(model_specs[name]) if kind is None]
        assert missing == [], f"{name} leaves {missing} untyped"


def test_fct_member_message_columns_match_fct_message():
    model_specs = models()
    assert shape(model_specs["fct_member_message"]) == shape(model_specs["fct_message"])


def test_fct_message_first_post_declared_columns_match_sql():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_message_first_post.sql").read_text()
    declared = [col for col, _ in shape(models()["fct_message_first_post"])]
    assert declared == ["user_id", "channel_id", "ts", "posted_at"]
    for col in declared:
        assert col in sql


def test_fct_member_message_sql_selects_star():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_member_message.sql").read_text()
    assert "select *" in sql.lower()


def test_fct_first_post_sql_full_outer_joins_archive_and_history_with_least():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_first_post.sql").read_text()
    assert "fct_message_first_post" in sql
    assert "fct_member_history" in sql
    assert "full outer join" in sql
    assert "least(" in sql


def test_fct_first_post_sql_uses_least_without_greatest():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_first_post.sql").read_text()
    assert "greatest(" not in sql
    assert sql.count("least(") == 1


def test_first_post_marts_declare_metric_version():
    import re

    marts = ("mart_channel_onboarding_scorecard", "mart_fast_reply_vs_retention",
             "mart_cohort_retention", "mart_cohort_survival")
    for name in marts:
        sql = (WAREHOUSE_DIR / "models" / "marts" / f"{name}.sql").read_text()
        assert re.search(r"'v\d+' as metric_version", sql), f"{name} has no metric_version"


def test_marts_do_not_read_first_post_search_columns():
    offenders = [p.name for p in (WAREHOUSE_DIR / "models" / "marts").glob("*.sql")
                 if "first_post_ts" in p.read_text() or "first_post_channel" in p.read_text()]
    assert offenders == [], "first post comes from fct_first_post, which takes the earlier source"


def test_cohort_marts_reference_fct_first_post():
    for name in ("mart_monthly_cohorts", "mart_newcomer_channels"):
        sql = (WAREHOUSE_DIR / "models" / "marts" / f"{name}.sql").read_text()
        assert "ref('fct_first_post')" in sql, f"{name} no longer anchors on the merged first post"


def test_fct_member_day_sql_uses_archive_models_and_excludes_snapshot_models():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_member_day.sql").read_text()
    assert "fct_member_message" in sql, "the day grain has to come from the archive"
    assert "fct_first_post" in sql, "a day offset needs the merged first post"
    assert "fct_member_activity" not in sql, "that is Slack's snapshot, not the archive"
    assert "dim_member" not in sql, "author_kind already excludes bots; dim_member is empty in dev"


def test_fct_member_retention_sql_reads_fct_member_day_not_fct_member_activity():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_member_retention.sql").read_text()
    assert "fct_member_day" in sql, "retention reads posting days from the archive"
    assert "fct_member_activity" not in sql, (
        "the member-day snapshot starts part way through the history and has gaps, "
        "which blanked whole cohorts behind the coverage floor"
    )


def test_mart_member_day_is_view_over_fct_member_day():
    sql = (WAREHOUSE_DIR / "models" / "marts" / "mart_member_day.sql").read_text()
    assert "materialized='view'" in sql, "a second copy of 3M rows earns nothing"
    assert "fct_member_day" in sql


def test_mart_cohort_survival_sql_declares_observable_columns():
    sql = (WAREHOUSE_DIR / "models" / "marts" / "mart_cohort_survival.sql").read_text()
    assert "as observable" in sql, "a cohort that has not aged must say so, not read zero"
    assert "newest_first_post" in sql, (
        "a day is observable only once every member of the cohort has lived through it"
    )
    assert "observed_through" in sql


def test_marts_do_not_use_source_macro():
    marts = (WAREHOUSE_DIR / "models" / "marts").glob("*.sql")
    offenders = [p.name for p in marts if "source(" in p.read_text()]
    assert offenders == []


def test_fct_member_channel_sql_uses_fct_member_message_and_excludes_search_sources():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_member_channel.sql").read_text()
    assert "fct_member_message" in sql
    assert "member_channel_message" not in sql
    assert "source(" not in sql


def test_fct_member_channel_sql_provides_columns_read_by_newcomer_channels_mart():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_member_channel.sql").read_text()
    mart = (WAREHOUSE_DIR / "models" / "marts" / "mart_newcomer_channels.sql").read_text()
    for col in ("user_id", "channel_id", "messages", "returned"):
        assert col in sql, f"fct_member_channel lost {col}"
        assert f"f.{col}" in mart or "c.user_id = f.user_id" in mart


def test_fct_member_channel_sql_casts_messages_to_integer():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_member_channel.sql").read_text()
    assert "count(*)::integer as messages" in sql


def test_mart_newcomer_channels_summed_messages_is_declared_bigint():
    import re

    import yaml

    marts = yaml.safe_load((WAREHOUSE_DIR / "models" / "marts" / "schema.yml").read_text())
    contracted = {m["name"]: m for m in marts["models"]
                  if m.get("config", {}).get("contract", {}).get("enforced")}
    assert "mart_newcomer_channels" in contracted

    declared = {c["name"]: c.get("data_type")
                for c in contracted["mart_newcomer_channels"]["columns"]}
    assert declared["newcomer_messages"] == "bigint"

    mart = (WAREHOUSE_DIR / "models" / "marts" / "mart_newcomer_channels.sql").read_text()
    summed = re.search(r"sum\(f\.messages\)", mart)
    assert summed, "the mart no longer sums f.messages; recheck the declared type"


def test_fct_first_response_sql_is_materialized_as_table_or_incremental():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_first_response.sql").read_text()
    assert "materialized='table'" in sql or "materialized='incremental'" in sql, (
        "fct_first_response joins fct_message twice over 50M rows and has 6 tests; "
        "as a view each test recomputes the whole chain"
    )


def test_fct_first_response_sql_declares_unique_index_on_newcomer_id():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_first_response.sql").read_text()
    assert "'columns': ['newcomer_id']" in sql
    assert "'unique': True" in sql


def test_lifetime_message_marts_read_fct_member_lifetime_messages():
    marts = ("mart_participation_concentration", "mart_activity_distribution",
             "mart_onboarding_recurrence_funnel", "mart_monthly_cohorts")
    for name in marts:
        sql = (WAREHOUSE_DIR / "models" / "marts" / f"{name}.sql").read_text()
        assert "fct_member_lifetime_messages" in sql, f"{name} still on the Slack window"
        assert "channel_messages_posted" not in sql, f"{name} still reads the windowed count"


def test_fct_member_lifetime_messages_sql_reads_month_messages():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_member_lifetime_messages.sql").read_text()
    assert "fct_member_month_messages" in sql
    assert "fct_member_window" not in sql
    assert "::integer" in sql


def test_lifetime_message_marts_have_expected_metric_versions():
    expected_versions = {"mart_participation_concentration": "v5", "mart_activity_distribution": "v18",
                         "mart_onboarding_recurrence_funnel": "v17", "mart_monthly_cohorts": "v4",
                         "mart_newcomer_channels": "v5"}
    for name, version in expected_versions.items():
        sql = (WAREHOUSE_DIR / "models" / "marts" / f"{name}.sql").read_text()
        assert f"'{version}' as metric_version" in sql, f"{name} is not at {version}"


def test_mart_top_posters_sql_excludes_display_name():
    sql = (WAREHOUSE_DIR / "models" / "marts" / "mart_top_posters.sql").read_text()
    assert "display_name" not in sql
    assert "fct_member_month_messages" in sql
    assert "fct_top_posters" not in sql


def test_response_marts_read_fct_first_response_not_first_reply_models():
    for name in ("mart_fast_reply_vs_retention", "mart_channel_onboarding_scorecard",
                 "mart_response_rate"):
        sql = (WAREHOUSE_DIR / "models" / "marts" / f"{name}.sql").read_text()
        assert "fct_first_response" in sql, f"{name} not cut over"
        assert "fct_first_reply" not in sql, f"{name} still on the search crawl"
        assert "fct_member_first_reply" not in sql, f"{name} still on the search crawl"


def test_response_marts_have_expected_metric_versions():
    expected_versions = {"mart_top_posters": "v4", "mart_fast_reply_vs_retention": "v11",
                         "mart_channel_onboarding_scorecard": "v9", "mart_response_rate": "v3"}
    for name, version in expected_versions.items():
        sql = (WAREHOUSE_DIR / "models" / "marts" / f"{name}.sql").read_text()
        assert f"'{version}' as metric_version" in sql, f"{name} is not at {version}"


def test_mart_response_rate_sql_filters_newcomers_by_cohort_at_and_account_flags():
    sql = (WAREHOUSE_DIR / "models" / "marts" / "mart_response_rate.sql").read_text()
    assert "cohort_at" in sql, (
        "the archive's first post is the oldest message it holds, so a member who lurked "
        "for years lands in whatever month they finally posted; gate on the join date"
    )
    for account_flag in ("is_bot", "is_deleted", "invite_pending"):
        assert account_flag in sql, f"mart_response_rate counts {account_flag} accounts as newcomers"


def test_fct_first_response_sql_selects_bot_at_and_fails_on_schema_change():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_first_response.sql").read_text()
    assert "t.bot_at as bot_at" in sql, (
        "mart_response_rate splits bot_replied_first from bot_first_then_member, "
        "which needs the bot timestamp to compare against responded_at"
    )
    assert "on_schema_change='fail'" in sql, (
        "on the default 'ignore' a new column never reaches the table and on "
        "'append_new_columns' it arrives null for every row already built; either way "
        "bot_replied_first reads zero for all of history, so fail and force a full refresh"
    )


def test_archive_schema_migration_indexes_response_join_columns():
    sql = (MIGRATIONS_DIR / "0089_archive_schema.sql").read_text()
    assert "archive.message (channel_id, thread_root_ts)" in sql, (
        "fct_first_response joins fct_message on (channel_id, thread_root_ts); without the "
        "index that is a sequential scan over every message in the workspace, on every "
        "nightly run"
    )
    assert "archive.message (channel_id, posted_at)" in sql, (
        "the in-channel mention join walks one channel's hour after the first post"
    )


def test_fct_first_response_sql_is_incremental_with_lookback_hours():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_first_response.sql").read_text()
    assert "materialized='incremental'" in sql
    assert "unique_key='newcomer_id'" in sql
    assert "is_incremental()" in sql
    assert "lookback_hours" in sql, (
        "an unanswered first post can become answered later, so the window must reach back"
    )


def test_fct_message_models_are_materialized_as_views():
    for name in ("fct_message", "fct_member_message"):
        sql = (WAREHOUSE_DIR / "models" / "staging" / f"{name}.sql").read_text()
        assert "materialized='view'" in sql, (
            f"{name} as a table is a 21 GB second copy of the archive, rewritten on every "
            "build and a day old between nightly builds; post pages read it and need it live"
        )
        assert "is_incremental()" not in sql


def test_archive_has_no_mark_deleted_and_fct_message_sql_has_no_deleted_at():
    from lib import archive

    assert not hasattr(archive, "mark_deleted")
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_message.sql").read_text()
    assert "deleted_at" not in sql, (
        "the archive records no deletion, so the spine carries neither a filter nor a sweep "
        "for one; both come back together if it ever does"
    )


def test_body_of_deletion_envelope_returns_none():
    from lib import archive

    assert archive.body_of({"type": "message", "subtype": archive.DELETED_SUBTYPE}) is None, (
        "body_of must keep returning None for a deletion envelope, or it falls through and "
        "the wrapper is recorded as if it were a message"
    )


def test_body_of_changed_envelope_returns_inner_message():
    from lib import archive

    inner = {"ts": "1.1", "text": "after"}
    envelope = {"type": "message", "subtype": archive.CHANGED, "message": inner}
    assert archive.body_of(envelope) == inner


def test_archive_message_change_markers_migration_indexes_updated_at():
    sql = (MIGRATIONS_DIR / "0095_archive_message_change_markers.sql").read_text()
    assert "archive.message (updated_at)" in sql, "checks/archive.py reads max(updated_at)"


def test_staging_schema_omits_expression_unique_test_and_archive_has_primary_key():
    schema = (WAREHOUSE_DIR / "models" / "staging" / "schema.yml").read_text()
    assert "channel_id || '-' || ts" not in schema, (
        "the expression test cost 225.78s on fct_message and 191.22s on fct_member_message "
        "to re-prove what the unique index already guarantees"
    )
    sql = (MIGRATIONS_DIR / "0089_archive_schema.sql").read_text()
    assert "PRIMARY KEY (channel_id, ts)" in sql, "something has to enforce it, and the archive does"




def test_drop_onboarding_funnel_migration_drops_table_and_model_is_absent():
    sql = (MIGRATIONS_DIR / "0096_drop_onboarding_funnel.sql").read_text()
    assert "DROP TABLE IF EXISTS analytics.mart_onboarding_funnel" in sql
    models = {p.stem for p in (WAREHOUSE_DIR / "models").rglob("*.sql")}
    assert "mart_onboarding_funnel" not in models, "dropping a model dbt still builds would loop"


def test_mart_fast_reply_vs_retention_sql_classifies_bot_reply_separately():
    sql = (WAREHOUSE_DIR / "models" / "marts" / "mart_fast_reply_vs_retention.sql").read_text()
    assert "when not r.answered or r.bot_replied then 'none'" not in sql, (
        "that or also swallowed newcomers a member did answer, whenever a bot replied too"
    )
    assert "when r.bot_replied then 'bot'" in sql
    assert "'v11' as metric_version" in sql


def test_mart_channel_onboarding_scorecard_sql_counts_fast_reply_when_bot_replied():
    sql = (WAREHOUSE_DIR / "models" / "marts" / "mart_channel_onboarding_scorecard.sql").read_text()
    assert "and not bot_replied as fast_reply" not in sql
    assert "'v9' as metric_version" in sql


def test_mart_channel_bands_sql_selects_band_top_and_home_helper_reads_band_top():
    sql = (WAREHOUSE_DIR / "models" / "marts" / "mart_channel_bands.sql").read_text()
    assert "band_top" in sql, "the mart has to publish the edge Rails used to hold"
    helper = (WAREHOUSE_DIR.parent / "web" / "app" / "helpers" / "home_helper.rb").read_text()
    assert "BAND_TOP" not in helper, "Rails declared dbt's ladder a third time"
    assert ".band_top" in helper


def test_fct_member_retention_sql_names_posted_within_30d_of_joining_column():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_member_retention.sql").read_text()
    assert "posted_within_30d_of_joining" in sql, "one anchors on cohort_at, the other on first_post_on"
    assert "as posted_within_30d\n" not in sql


def test_fct_member_retention_sql_is_incremental_with_90_day_window():
    sql = (WAREHOUSE_DIR / "models" / "staging" / "fct_member_retention.sql").read_text()
    assert "materialized='incremental'" in sql
    assert "settles_after_days = 90" in sql, (
        "day_90_covered flips up to 90 days after a first post, so a shorter window "
        "would freeze a stale false"
    )
    assert "not exists (select 1 from {{ this }}" in sql


def test_hot_staging_models_are_materialized_as_tables():
    for name in ("fct_first_post", "fct_message_first_post", "fct_member_channel"):
        sql = (WAREHOUSE_DIR / "models" / "staging" / f"{name}.sql").read_text()
        assert "materialized='table'" in sql, f"{name} is still re-derived once per test"


def test_spine_marts_read_fct_message_hour_not_fct_message():
    for name in ("mart_activity_clock", "mart_channel_clock",
                 "mart_archive_day_coverage", "mart_archive_channel_coverage"):
        sql = (WAREHOUSE_DIR / "models" / "marts" / f"{name}.sql").read_text()
        assert "fct_message_hour" in sql, f"{name} still aggregates the spine directly"
    for name in ("mart_activity_clock", "mart_channel_clock"):
        sql = (WAREHOUSE_DIR / "models" / "marts" / f"{name}.sql").read_text()
        assert "ref('fct_message')" not in sql, f"{name} still touches 54M rows for its window edge"


def test_fct_message_hour_and_month_messages_are_incremental_with_observed_through():
    for name in ("fct_message_hour", "fct_member_month_messages"):
        sql = (WAREHOUSE_DIR / "models" / "staging" / f"{name}.sql").read_text()
        assert "materialized='incremental'" in sql
        assert "observed_through" in sql, f"{name} has no watermark to window on"
        assert "is_incremental()" in sql
