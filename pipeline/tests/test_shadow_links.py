import pytest

from jobs import shadow_links


def test_a_variant_replaces_nested_keys_and_keeps_the_rest():
    base = {"scoring": {"floor": 3.0, "strong": 5.0}, "identity_signals": {"mailbox_alias": {"weight": 6.0, "crowd_ceiling": 20}}}

    merged = shadow_links.overlay(base, {"identity_signals": {"mailbox_alias": {"weight": 8.0}}})

    assert merged["identity_signals"]["mailbox_alias"] == {"weight": 8.0, "crowd_ceiling": 20}
    assert merged["scoring"] == {"floor": 3.0, "strong": 5.0}
    assert base["identity_signals"]["mailbox_alias"]["weight"] == 6.0


def test_a_null_removes_a_key_and_a_list_is_replaced_whole():
    base = {"name_signals": {"handle_stem_long": {"weight": 2.0}, "full_name": {"weight": 3.0}},
            "staff_domains": ["hackclub.com"]}

    merged = shadow_links.overlay(base, {"name_signals": {"handle_stem_long": None},
                                         "staff_domains": ["hackclub.com", "example.org"]})

    assert merged["name_signals"] == {"full_name": {"weight": 3.0}}
    assert merged["staff_domains"] == ["hackclub.com", "example.org"]


def test_the_variant_is_named_after_its_file_unless_named():
    assert shadow_links.variant_name("variants/flat_inbox.yml") == "flat_inbox"
    assert shadow_links.variant_name("variants/x.yml", "ip_burst_strong") == "ip_burst_strong"
    for path, name in (("variants/live.yml", None), ("variants/Flat Inbox.yml", None), ("x.yml", "a;b")):
        with pytest.raises(ValueError):
            shadow_links.variant_name(path, name)


def test_a_variant_file_must_hold_a_mapping(tmp_path):
    listed = tmp_path / "listed.yml"
    listed.write_text("- one\n- two\n")

    with pytest.raises(ValueError):
        shadow_links.load_variant(listed)


def test_a_variant_builds_into_the_shadow_table_under_its_name(tmp_path, monkeypatch, capsys):
    path = tmp_path / "flat_inbox.yml"
    path.write_text("identity_signals:\n  mailbox_alias:\n    weight: 8.0\n")
    built = {}

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def build_shadow(_conn, config, variant):
        built.update(variant=variant, weight=config["identity_signals"]["mailbox_alias"]["weight"])
        return 12

    monkeypatch.setattr(shadow_links, "load_dotenv", lambda *_args: None)
    monkeypatch.setattr(shadow_links, "connect", lambda *_args: Conn())
    monkeypatch.setattr(shadow_links.links, "build_shadow", build_shadow)

    assert shadow_links.main(["--variant", str(path)]) == 0
    assert built == {"variant": "flat_inbox", "weight": 8.0}
    assert "12 link(s) written to fd.member_link_shadow as flat_inbox" in capsys.readouterr().out


def test_a_missing_variant_file_exits_2_without_connecting(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(shadow_links, "load_dotenv", lambda *_args: None)
    monkeypatch.setattr(shadow_links, "connect", lambda *_args: pytest.fail("connected"))

    assert shadow_links.main(["--variant", str(tmp_path / "nope.yml")]) == 2
    assert capsys.readouterr().err.startswith("links: ")


def test_a_bare_name_reads_the_variant_kept_in_db_link_variants():
    path = shadow_links.variant_path("baseline")

    assert path == shadow_links.VARIANTS_DIR / "baseline.yml"
    assert path.exists()
    assert shadow_links.variant_path("/tmp/x.yml") == shadow_links.pathlib.Path("/tmp/x.yml")


def test_every_kept_variant_loads_over_the_catalogue():
    for path in shadow_links.VARIANTS_DIR.glob("*.yml"):
        assert shadow_links.variant_name(path) == path.stem
        assert "identity_signals" in shadow_links.load_variant(path)
