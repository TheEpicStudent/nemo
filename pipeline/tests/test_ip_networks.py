import ipaddress
import os
import pathlib
import time

import pytest

from ingest import ip_networks as networks

CLASSES = {
    "vpn": {"names": ["Proton AG", "M247"], "asns": [36183]},
    "hosting": {"names": [], "asns": []},
    "rotating": {"names": ["Reliance Jio", "T-Mobile"], "asns": []},
}


def net(text):
    return ipaddress.ip_network(text, strict=False)


def range_lists(vpn=(), hosting=()):
    return {"vpn": networks.Ranges([net(one) for one in vpn]),
            "hosting": networks.Ranges([net(one) for one in hosting])}


def asn_lookup(asn=None, name=None, country=None):
    return lambda _network: {"asn": asn, "network": name, "country": country}


def test_classes_match_ip_networks_migration_check():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0183_ip_networks.sql").read_text()
    for name in networks.CLASSES:
        assert f"'{name}'" in sql


def test_ranges_merges_adjacent_networks_and_detects_overlap():
    ranges = networks.Ranges([net("10.0.0.0/28"), net("10.0.0.8/29"), net("192.168.0.0/16")])

    assert len(ranges) == 2
    assert ranges.overlaps(net("10.0.0.0/24"))
    assert ranges.overlaps(net("192.168.5.0/24"))
    assert not ranges.overlaps(net("10.0.1.0/24"))
    assert not ranges.overlaps(net("2001:db8::/64"))


def test_read_ranges_skips_blank_comment_and_invalid_lines():
    parsed = networks.read_ranges("# list\n1.2.3.0/24\n\nnot a range\n5.6.7.8 # one host\n")

    assert parsed == [net("1.2.3.0/24"), net("5.6.7.8/32")]


def test_prefix_of_address_returns_containing_prefix():
    assert networks.prefix_of("1.2.3.4") == net("1.2.3.0/24")
    assert networks.prefix_of("2001:db8::1") == net("2001:db8::/64")
    assert networks.as_network("1.2.3.0/24") == net("1.2.3.0/24")


def test_asn_number_parses_with_and_without_as_prefix():
    assert networks.asn_number("AS13335") == 13335
    assert networks.asn_number("13335") == 13335
    assert networks.asn_number("") is None
    assert networks.asn_number(None) is None


def test_curated_class_matches_asn_or_name_substring():
    assert networks.curated_class(36183, "Akamai Technologies, Inc.", CLASSES) == "vpn"
    assert networks.curated_class(9009, "M247 Europe SRL", CLASSES) == "vpn"
    assert networks.curated_class(55836, "Reliance Jio Infocomm Limited", CLASSES) == "rotating"
    assert networks.curated_class(7922, "Comcast Cable Communications, LLC", CLASSES) is None


def test_classify_tor_takes_precedence_over_other_classes():
    prefix = net("5.6.7.0/24")

    row = networks.classify(prefix, {prefix: "anomaly"}, range_lists(vpn=["5.6.7.0/24"]), CLASSES,
                            asn_lookup(9009, "M247"))
    listed = networks.classify(prefix, {prefix: "tor_list"}, range_lists(), CLASSES, asn_lookup(7922, "Comcast"))

    assert row[4:] == ("tor", "anomaly")
    assert listed[4:] == ("tor", "tor_list")


def test_classify_vpn_from_curated_class_or_vpn_list():
    curated = networks.classify(net("5.6.7.0/24"), set(), range_lists(), CLASSES, asn_lookup(62371, "Proton AG"))
    listed = networks.classify(net("5.6.7.0/24"), set(), range_lists(vpn=["5.6.7.128/25"]), CLASSES,
                               asn_lookup(7922, "Comcast"))

    assert curated[4:] == ("vpn", "curated")
    assert listed[4:] == ("vpn", "lists_vpn")


def test_classify_hosting_list_returns_hosting_and_carrier_returns_rotating():
    hosted = networks.classify(net("5.6.7.0/24"), set(), range_lists(hosting=["5.6.0.0/16"]), CLASSES,
                               asn_lookup(16276, "OVH SAS"))
    carrier = networks.classify(net("49.36.0.0/24"), set(), range_lists(), CLASSES,
                                asn_lookup(55836, "Reliance Jio Infocomm Limited", "IN"))

    assert hosted[4:] == ("hosting", "lists_vpn")
    assert carrier == ("49.36.0.0/24", 55836, "Reliance Jio Infocomm Limited", "IN", "rotating", "curated")


def test_classify_unlisted_network_returns_stable():
    known = networks.classify(net("73.0.0.0/24"), set(), range_lists(), CLASSES, asn_lookup(7922, "Comcast"))
    unknown = networks.classify(net("73.0.0.0/24"), set(), range_lists(), CLASSES, asn_lookup())

    assert known[4:] == ("stable", "ipinfo")
    assert unknown[4:] == ("stable", "default")


def test_download_cached_reuses_fresh_file_and_stale_file_on_failed_refresh(tmp_path, monkeypatch):
    cached = tmp_path / "list.txt"
    cached.write_text("1.2.3.0/24\n")

    def failing_urlopen(*_args, **_kwargs):
        raise OSError("offline")

    monkeypatch.setattr(networks.urllib.request, "urlopen", failing_urlopen)

    assert networks.download_cached("list.txt", "https://example.com", cache_dir=tmp_path) == cached
    stale_time = time.time() - networks.REFRESH_SECONDS - 60
    os.utime(cached, (stale_time, stale_time))
    assert networks.download_cached("list.txt", "https://example.com", cache_dir=tmp_path) == cached

    with pytest.raises(OSError):
        networks.download_cached("missing.txt", "https://example.com", cache_dir=tmp_path)


def test_run_without_ipinfo_token_returns_zero_and_prints_notice(monkeypatch, capsys):
    monkeypatch.delenv("IPINFO_TOKEN", raising=False)

    assert networks.run(object()) == 0
    assert "IPINFO_TOKEN is not set" in capsys.readouterr().out


class Rows:
    def __init__(self, answers):
        self.answers = answers
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        self.rows = self.answers.get(sql, [])
        return self

    def fetchall(self):
        return self.rows


def test_download_cached_tries_tor_project_first_then_mirror(tmp_path, monkeypatch):
    tried_urls = []

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, *_args):
            return b""

    def urlopen(url, timeout):
        tried_urls.append(url)
        if "torproject" in url:
            raise OSError("blocked")
        return Response()

    monkeypatch.setattr(networks.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(networks.shutil, "copyfileobj", lambda _source, out: out.write(b"1.2.3.4\n"))

    path = networks.download_cached("tor.txt", networks.TOR_EXIT_LISTS, cache_dir=tmp_path)

    assert tried_urls == list(networks.TOR_EXIT_LISTS)
    assert path.read_text() == "1.2.3.4\n"
    assert networks.TOR_EXIT_LISTS[0] == "https://check.torproject.org/torbulkexitlist"


def test_tor_exit_addresses_parses_valid_addresses_only(tmp_path, monkeypatch):
    listed = tmp_path / "tor.txt"
    listed.write_text("# tor_exits\n# Source File Date: today\n185.220.101.5\n2a0b:f4c2::5\n10.0.0.0/8\nnot an ip\n")
    monkeypatch.setattr(networks, "download_cached", lambda *_args, **_kwargs: listed)

    assert networks.tor_exit_addresses() == ["185.220.101.5", "2a0b:f4c2::5"]


def test_tor_exit_addresses_without_download_returns_empty_and_prints_notice(monkeypatch, capsys):
    def offline(*_args, **_kwargs):
        raise OSError("blocked")

    monkeypatch.setattr(networks, "download_cached", offline)

    assert networks.tor_exit_addresses() == []
    assert "Tor comes from Slack anomalies only" in capsys.readouterr().out


def test_tor_prefixes_returns_used_exit_and_anomaly_prefixes():
    conn = Rows({networks.USED_EXITS_SQL: [("185.220.101.5",)], networks.TOR_SQL: [("45.84.107.9",)]})

    prefixes = networks.tor_prefixes(conn, ["185.220.101.5", "86.54.28.7"])

    assert prefixes == {net("185.220.101.0/24"): "tor_list", net("45.84.107.0/24"): "anomaly"}
    assert conn.executed[0] == (networks.USED_EXITS_SQL, (["185.220.101.5", "86.54.28.7"],))
    assert "fd.login_event WHERE ip = ANY(%s::inet[])" in networks.USED_EXITS_SQL


def test_retagged_returns_tor_prefixes_not_in_already_set():
    tor = {net("185.220.101.0/24"): "tor_list", net("45.84.107.0/24"): "anomaly"}
    conn = Rows({networks.RETAG_SQL: [("185.220.101.0/24",), ("45.84.107.0/24",)]})

    retagged_prefixes = networks.retagged(conn, tor, {net("45.84.107.0/24")})

    assert retagged_prefixes == [net("185.220.101.0/24")]
    assert "class <> 'tor'" in networks.RETAG_SQL
    assert networks.retagged(Rows({}), {}, set()) == []


def test_ip_network_tor_list_migration_adds_tor_list_source():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0217_ip_network_tor_list.sql").read_text()

    assert "'anomaly', 'tor_list', 'curated', 'lists_vpn', 'ipinfo', 'default'" in sql
