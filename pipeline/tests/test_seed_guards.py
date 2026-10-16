import pytest

from seed.guards import SeedRefusedError, check_target_name, target_allowed


@pytest.mark.parametrize("dbname", ["mnemosyne_dev", "mnemosyne_test", "anything_seed"])
def test_target_allowed_with_seed_suffix_returns_true(dbname):
    assert target_allowed(dbname)


@pytest.mark.parametrize(
    "dbname",
    [
        "mnemosyne",
        "",
        "postgres",
        "mnemosyne_devious",
        "mnemosyne_dev_backup",
        "dev",
        "MNEMOSYNE_DEV",
    ],
)
def test_target_allowed_with_other_name_returns_false(dbname):
    assert not target_allowed(dbname)


def test_target_allowed_with_matching_allow_returns_true():
    assert target_allowed("mnemosyne", allow="mnemosyne")


def test_target_allowed_with_mismatched_allow_returns_false():
    assert not target_allowed("mnemosyne", allow="mnemosyne_dev")
    assert not target_allowed("mnemosyne_other", allow="mnemosyne")


def test_check_target_name_refused_raises_seed_refused_error_naming_database():
    with pytest.raises(SeedRefusedError, match="mnemosyne is not a seed target"):
        check_target_name("mnemosyne", allow="")


def test_verify_checks_resolve_in_profile_file():
    import json

    from seed import verify
    from seed.profile import PROFILE_FILE

    profile = json.loads(PROFILE_FILE.read_text())
    paths = ([path for path, _, _ in verify.SHAPE_CHECKS]
             + [size for _, _, size in verify.SHAPE_CHECKS]
             + [path for path, _, _ in verify.QUANTILE_CHECKS])

    for path in sorted(set(paths)):
        try:
            verify.get_path(profile, path)
        except KeyError:
            pytest.fail(
                f"verify.py checks {path!r} but profile.json has no such key, so "
                "`nemo seed` dies on a KeyError after the whole build has already run"
            )
