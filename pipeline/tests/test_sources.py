import pytest

from jobs import nightly_sync
from lib import sources


def test_sources_declare_all_required_fields():
    for key in sources.KEYS:
        spec = sources.source(key)
        missing = [field for field in sources.DECLARED if field not in spec]
        assert not missing, f"{key} declares no {', '.join(missing)}"


def test_sources_declared_values_are_in_allowed_sets():
    for key in sources.KEYS:
        spec = sources.source(key)
        assert spec["cadence"] in sources.CADENCES, key
        assert spec["guard"] in sources.GUARDS, key
        assert spec["resume"] in sources.RESUMES, key
        assert spec["retention"] in sources.RETENTIONS, key


def test_sources_retention_is_never_prune():
    for key in sources.KEYS:
        assert sources.source(key)["retention"] != "prune", key


def test_prune_floor_requires_keep_retention():
    for key in sources.KEYS:
        if sources.prune_floor(key):
            assert sources.source(key)["retention"] == "keep", key


def test_key_for_run_maps_run_names_to_source_keys():
    assert sources.key_for_run("channel_roster") == "channel_roster"
    assert sources.key_for_run("autojoin") == "channel_roster"
    assert sources.key_for_run("channel_info_names") == "channel_names"
    assert sources.key_for_run("admin_analytics_api:member") == "member_days"
    assert sources.key_for_run("admin_analytics_api:public_channel") == "channel_days"
    assert sources.key_for_run("admin_analytics_channel_month") == "channel_month"
    assert sources.key_for_run("nightly_sync") == "nightly_sync"


def test_parser_version_unknown_source_defaults_to_one():
    assert sources.parser_version("member_days") == 1
    assert sources.parser_version("not_a_source") == 1


def test_nightly_stages_match_declared_non_standalone_sources():
    stage_names = {name for name, _ in nightly_sync.stages()}
    assert stage_names <= set(sources.KEYS), "a stage must be a declared source"
    assert set(sources.KEYS) - stage_names == set(sources.STANDALONE_SOURCES), (
        "a declared source missing from the nightly must carry standalone: true in "
        "db/sources.yml, its own always-on worker rather than a nightly stage"
    )


def test_nightly_keys_exclude_standalone_sources():
    assert set(sources.NIGHTLY_KEYS) == set(sources.KEYS) - set(sources.STANDALONE_SOURCES)
    assert set(sources.NIGHTLY_KEYS) == {name for name, _ in nightly_sync.stages()}


def test_source_limits_default_within_min_and_max():
    for key in sources.KEYS:
        for name, bounds in (sources.source(key).get("limits") or {}).items():
            assert bounds["min"] <= bounds["default"] <= bounds["max"], f"{key}.{name}"


def test_clamped_limits_value_to_bounds():
    assert sources.clamped("channel_membership", "batch", 5) == 50
    assert sources.clamped("channel_membership", "batch", 9000) == 2000
    assert sources.clamped("channel_membership", "batch", 750) == 750
    assert sources.clamped("channel_membership", "batch", None) == 600


def test_source_unknown_key_raises_unknown_source_error():
    with pytest.raises(sources.UnknownSourceError):
        sources.source("teleporter")
    with pytest.raises(sources.UnknownSourceError):
        sources.limit("team_stats", "batch")


def test_num_found_guard_sources_enforce_short_at_floor():
    import re

    from lib import sources
    from lib.paths import PACKAGE_ROOT

    num_found_guarded = {key for key in sources.KEYS if sources.SOURCES[key].get("guard") == "num_found"}
    ingest_source = "\n".join(p.read_text() for p in (PACKAGE_ROOT / "ingest").glob("*.py"))
    unfloored = set(re.findall(r"(\w+_SHORT_AT)\s*=\s*NO_FLOOR", ingest_source))
    assert "MEMBER_SHORT_AT" in unfloored
    assert "member_days" not in num_found_guarded


def test_member_days_guard_is_none():
    from lib import sources

    assert sources.field_of("member_days", "guard") == "none"


def test_declared_guards_are_in_guards_vocabulary():
    from lib import sources

    for key in sources.KEYS:
        assert sources.SOURCES[key]["guard"] in sources.GUARDS


def test_dbt_error_class_values_match_declared_fault_classes():
    import re

    import yaml

    from lib.paths import DB_DIR, WAREHOUSE_DIR

    declared = set(yaml.safe_load((DB_DIR / "faults.yml").read_text())["classes"])
    schema = (WAREHOUSE_DIR / "models" / "staging" / "schema.yml").read_text()
    listed = re.search(r"error_class.*?values: \[(.*?)\]", schema, re.S)
    assert listed, "the error_class accepted_values block moved"
    accepted = {name.strip() for name in listed.group(1).split(",")}
    assert accepted == declared, (
        f"dbt accepts {sorted(accepted)} but db/faults.yml declares {sorted(declared)}"
    )


FULL_BUILD_SOURCES = {"dbt"}


def warehouse_models():
    import re

    from lib.paths import WAREHOUSE_DIR

    models = {}
    for path in (WAREHOUSE_DIR / "models").rglob("*.sql"):
        if "target" in path.parts:
            continue
        body = path.read_text()
        models[path.stem] = (
            {tuple(pair) for pair in re.findall(r"source\(\s*'([^']+)'\s*,\s*'([^']+)'\s*\)", body)},
            set(re.findall(r"ref\(\s*'([^']+)'\s*\)", body)),
        )
    return models


def downstream_models(models, tables):
    downstream = {name for name, (read, _) in models.items() if read & tables}
    changed = True
    while changed:
        changed = False
        for name, (_, refs) in models.items():
            if name not in downstream and refs & downstream:
                downstream.add(name)
                changed = True
    return downstream


def test_feeds_entries_are_warehouse_models_downstream_of_writes():
    models = warehouse_models()
    for key in sources.KEYS:
        if key in FULL_BUILD_SOURCES:
            continue
        spec = sources.source(key)
        tables = {tuple(w.split(".", 1)) for w in spec["writes"] if "." in w}
        downstream = downstream_models(models, tables)
        for fed_model in spec["feeds"]:
            assert fed_model in models, f"{key} says it feeds {fed_model}, which is not a warehouse model"
            assert fed_model in downstream, (
                f"{key} says it feeds {fed_model}, but nothing downstream of {sorted(tables)} reads it"
            )


def test_full_build_sources_write_analytics_only():
    for key in FULL_BUILD_SOURCES:
        assert sources.source(key)["writes"] == ["analytics"], key
