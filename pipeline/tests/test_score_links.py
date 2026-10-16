import pytest
from psycopg import errors

from jobs import score_links as links
from lib.graph import components

THRESHOLDS = {"floor": 3.0, "strong": 5.0, "certain": 8.0}


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class Conn:
    def __init__(self, answers):
        self.answers = answers

    def execute(self, query, params=None):
        text = query if isinstance(query, str) else query.as_string(None)
        for marker, rows in self.answers.items():
            if marker in text:
                return Result(rows(params) if callable(rows) else rows)
        raise AssertionError(f"unexpected query: {text}")


def test_mailbox_gmail_dots_and_plus_tag_fold_to_canonical_address():
    assert links.mailbox("A.B+x@GoogleMail.com") == "ab@gmail.com"
    assert links.mailbox("ab@gmail.com") == "ab@gmail.com"


def test_mailbox_non_gmail_domain_keeps_dots():
    assert links.mailbox("a.b+x@school.edu") == "a.b@school.edu"


def test_mailbox_invalid_address_returns_none():
    assert links.mailbox("nope") is None
    assert links.mailbox("+x@gmail.com") is None
    assert links.mailbox(None) is None


def test_staff_domain_matches_exact_and_subdomain_not_suffix():
    assert links.staff_domain("hackclub.com", ["hackclub.com"])
    assert links.staff_domain("mail.hackclub.com", ["hackclub.com"])
    assert not links.staff_domain("nothackclub.com", ["hackclub.com"])


def test_alias_pairs_staff_domains_are_excluded():
    rows = [("U3", "a.b@gmail.com"), ("U1", "ab+z@gmail.com"), ("U2", "x@hackclub.com"),
            ("U4", "x+1@hackclub.com"), ("U5", "solo@x.org")]

    assert links.alias_pairs(rows, ["hackclub.com"]) == {("U1", "U3")}


def test_components_chained_pairs_merge_into_one_group():
    assert components([("U1", "U2"), ("U3", "U2"), ("U7", "U8")]) == [
        {"U1", "U2", "U3"}, {"U7", "U8"}]


def test_linked_count_returns_largest_linked_group_size():
    person = {"U1", "U2", "U3", "U4"}

    assert links.linked_count(person, [("U1", "U2"), ("U2", "U3"), ("U4", "U9")]) == 3
    assert links.linked_count(person, []) == 0


def test_primary_account_returns_account_in_most_pairs():
    assert links.primary_account({"U1", "U2", "U3", "U5"}, {("U1", "U5"), ("U2", "U5"), ("U3", "U5")}) == "U5"


def test_band_of_score_maps_to_threshold_band():
    assert links.band_of(9, THRESHOLDS) == "certain"
    assert links.band_of(5, THRESHOLDS) == "strong"
    assert links.band_of(3, THRESHOLDS) == "weak"


def test_links_table_unqualified_or_uppercase_name_raises_value_error():
    assert links.links_table("fd.member_link").as_string(None) == '"fd"."member_link"'
    for name in ("member_link", "fd.member_link;drop", "FD.member_link", ""):
        with pytest.raises(ValueError):
            links.links_table(name)


def test_measure_returns_bands_verdicts_groups_aliases_recall_and_samples(monkeypatch):
    monkeypatch.setattr(links, "scoring", lambda: THRESHOLDS)
    monkeypatch.setattr(links, "catalogue", lambda: {"staff_domains": ["hackclub.com"]})
    linked_pairs = [("U1", "U2", 9.0), ("U2", "U3", 4.0), ("U6", "U7", 5.5)]
    query_params = {}
    conn = Conn({
        "FROM fd.link_sample s": [("strong", 50, 9, 1), ("certain", 50, 0, 0)],
        "count(*) FILTER": [(1, 2, 3)],
        "FROM fd.member_link_verdict": [
            ("U1", "U2", "same_person", 9.0, "mailbox_alias"), ("U2", "U3", "same_person", 4.0, "ip_burst"),
            ("U3", "U4", "same_person", None, None), ("U5", "U8", "different_people", None, None)],
        "'user_deactivated'": lambda params: query_params.update(params) or [
            ("U10", "U11", 9.0, "mailbox_alias", ["inbox"]), ("U12", "U13", None, None, ["VPN exit"])],
        "ANY(%(ids)s)": lambda params: [row for row in linked_pairs
                                        if row[0] in params["ids"] and row[1] in params["ids"]],
        "FROM fd.member_identity": [("U6", "a.b@gmail.com"), ("U7", "ab@gmail.com"),
                                    ("U8", "x@hackclub.com"), ("U9", "x+1@hackclub.com")],
    })

    result = links.measure(conn)

    assert result["bands"] == {"certain": 1, "strong": 2, "weak": 3}
    same = result["verdicts"]["same_person"]
    assert (same["pairs"], same["linked"]) == (3, 2)
    assert same["bands"] == {"certain": 1, "weak": 1}
    assert result["verdicts"]["allowed_alt"]["pairs"] == 0
    assert result["groups"] == [
        {"primary_account": "U2", "accounts": 4, "linked": 3, "strong_linked": 2}]
    assert (result["aliases"]["pairs"], result["aliases"]["linked"]) == (1, 1)
    assert result["aliases"]["bands"] == {"strong": 1}
    assert query_params == {"bot_user_ids": ["USLACKBOT", "U09ULFV88KU"], "reban_window_days": 30,
                     "home_ip_max_users": 8, "vpn_ip_max_users": 10}
    post_ban = result["recall"]["post-ban"]
    assert (post_ban["pairs"], post_ban["found"]) == (2, 1)
    assert post_ban["evidence"] == {"inbox": (1, 1), "VPN exit": (0, 1)}
    same = result["recall"]["same person"]
    assert (same["pairs"], same["found"]) == (3, 1)
    assert same["signals"] == {"mailbox_alias": (1, 1), "ip_burst": (0, 1)}
    assert list(result["samples"]) == ["certain", "strong"]
    assert result["samples"]["strong"] == {"drawn": 50, "right": 9, "wrong": 1, "target": None}


def test_recall_counts_found_pairs_by_band_signal_and_evidence():
    items = [(9.0, "mailbox_alias", ("inbox",)), (6.0, "ip_stable", ("home address", "inbox")),
             (4.0, "ip_burst", ("VPN exit",)), (None, None, ("VPN exit",))]

    recall_result = links.recall(items, THRESHOLDS)

    assert (recall_result["pairs"], recall_result["found"]) == (4, 2)
    assert recall_result["bands"] == {"certain": 1, "strong": 1, "weak": 1, "not linked": 1}
    assert recall_result["signals"] == {"mailbox_alias": (1, 1), "ip_stable": (1, 1), "ip_burst": (0, 1)}
    assert recall_result["evidence"] == {"inbox": (2, 2), "home address": (1, 1), "VPN exit": (0, 2)}


def test_post_ban_sql_requires_admin_ban_reactivation_and_shared_mailbox():
    text = links.POST_BAN_SQL

    assert "d.action = 'user_deactivated' AND NOT d.ours" in text
    assert "d.actor_id <> d.entity_id AND d.actor_id <> ALL(%(bot_user_ids)s)" in text
    assert "r.action = 'user_reactivated'" in text and "r.at > d.deactivated_at" in text
    assert "deactivated_at <= joined_at + make_interval(days => %(reban_window_days)s)" in text
    assert text.count("r.joined_at > b.deactivated_at") == 2
    assert "tb.kind = 'mailbox'" in text and "tr.value = tb.value" in text


def test_post_ban_sql_vpn_exit_needs_same_build_and_rotating_ips_excluded():
    text = links.POST_BAN_SQL

    assert "(ub.ip_class = 'home' OR ur.ua_id = ub.ua_id)" in text
    assert "WHEN n.class IN ('rotating', 'tor') THEN NULL" in text
    assert "SELECT 1 FROM fd.shared_ip s WHERE s.ip = e.ip) THEN NULL" in text
    assert "CASE p.ip_class WHEN 'home' THEN %(home_ip_max_users)s" in text
    assert "ELSE %(vpn_ip_max_users)s END" in text
    assert "LEFT JOIN {links} l" in text


def test_render_recall_results_prints_counts_and_breakdowns():
    recall = {"pairs": 4, "found": 2, "bands": {"certain": 1, "strong": 1, "not linked": 2},
              "signals": {"mailbox_alias": (1, 1), "ip_burst": (0, 1)},
              "evidence": {"inbox": (2, 2), "VPN exit": (0, 2)}}
    result = {
        "links": "fd.member_link",
        "bands": {"certain": 1, "strong": 1, "weak": 0},
        "recall": {"post-ban": recall, "same person": {**recall, "evidence": {}}},
        "verdicts": {},
        "groups": [],
        "aliases": {"pairs": 0, "linked": 0, "bands": {}},
    }

    text = "\n".join(links.render(result))

    assert "  post-ban               2 of 4       50%  certain 1, strong 1, weak 0, not linked 2" in text
    assert "by evidence         VPN exit 0 of 2, inbox 2 of 2" in text
    assert "by top signal       ip_burst 0 of 1, mailbox_alias 1 of 1" in text
    assert text.count("by evidence") == 1


def test_render_counts_print_percentages():
    result = {
        "links": "fd.member_link",
        "bands": {"certain": 1, "strong": 2, "weak": 3},
        "verdicts": {"same_person": {"pairs": 4, "linked": 2, "bands": {"certain": 2}}},
        "groups": [{"primary_account": "U2", "accounts": 4, "linked": 3, "strong_linked": 2}],
        "aliases": {"pairs": 0, "linked": 0, "bands": {}},
    }

    text = "\n".join(links.render(result))

    assert "links in fd.member_link: 6 (certain 1, strong 2, weak 3)" in text
    assert "same_person" in text and "2 of 4" in text and "50%" in text
    assert "3 linked together (75%)" in text
    assert "email aliases outside staff domains: 0 of 0 linked (n/a)" in text


def test_main_invalid_links_table_returns_2_without_connecting(monkeypatch, capsys):
    monkeypatch.setattr(links, "load_dotenv", lambda *_args: None)
    monkeypatch.setattr(links, "connect", lambda *_args: pytest.fail("connected"))

    assert links.main(["--links", "fd.member_link;drop"]) == 2
    assert "not a schema.table name" in capsys.readouterr().err


def test_main_missing_links_table_returns_2_with_database_error(monkeypatch, capsys):
    class Missing:
        read_only = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, *_args):
            raise errors.UndefinedTable('relation "fd.nope" does not exist\nLINE 4: FROM "fd"."nope"')

    monkeypatch.setattr(links, "load_dotenv", lambda *_args: None)
    monkeypatch.setattr(links, "scoring", lambda: THRESHOLDS)
    monkeypatch.setattr(links, "catalogue", lambda: {})
    monkeypatch.setattr(links, "connect", lambda *_args: Missing())

    assert links.main(["--links", "fd.nope"]) == 2
    assert capsys.readouterr().err == 'check-links: relation "fd.nope" does not exist\n'


TARGETS = {"least_verdicts": 2, "precision": {"floor": 0.5, "strong": 0.9, "certain": 0.98}}


def test_labelled_same_person_is_right_and_allowed_alt_is_excluded():
    rows = [("U1", "U2", "same_person", 9), ("U1", "U3", "different_people", 4),
            ("U1", "U4", "allowed_alt", 8), ("U1", "U5", "different_people", None)]

    assert links.labelled(rows) == [(9.0, True), (4.0, False), (None, False)]


def test_suggest_cutoffs_returns_lowest_score_reaching_target_precision():
    pairs = [(9.0, True), (8.5, True), (6.0, True), (6.0, False), (4.0, True), (4.0, False),
             (3.5, False), (None, True), (None, False)]

    suggestion = links.suggest_cutoffs(pairs, TARGETS)

    assert suggestion["enough"] and (suggestion["right"], suggestion["wrong"]) == (5, 4)
    assert suggestion["cuts"]["floor"]["cut"] == 3.5
    assert suggestion["cuts"]["strong"]["cut"] == 8.5
    assert suggestion["cuts"]["certain"]["cut"] == 8.5
    assert suggestion["cuts"]["strong"]["recall"] == 2 / 5


def test_suggest_cutoffs_too_few_verdicts_returns_no_cuts():
    suggestion = links.suggest_cutoffs([(9.0, True), (3.0, False)], TARGETS)

    assert not suggestion["enough"]
    assert suggestion["cuts"] == {}


def test_render_cutoffs_prints_current_and_suggested_cut():
    result = {
        "links": "fd.member_link",
        "bands": {"certain": 1, "strong": 1, "weak": 1},
        "verdicts": {},
        "groups": [],
        "aliases": {"pairs": 0, "linked": 0, "bands": {}},
        "marks": {"floor": 3.0, "strong": 5.0, "certain": 8.0},
        "cutoffs": {"right": 5, "wrong": 4, "enough": True,
                    "cuts": {"strong": {"cut": 8.5, "precision": 1.0, "recall": 0.4}}},
    }

    text = "\n".join(links.render(result))

    assert "bands from verdicts: 5 same person, 4 different people" in text
    assert "strong   now 5, suggested 8.5 (precision 100%, recall 40%)" in text
    assert "floor    now 3, no score reaches the target precision" in text


def test_draw_sql_partitions_by_band_and_top_signal_and_excludes_drawn_links():
    text = links.DRAW_SQL

    assert "PARTITION BY b.band, b.top_signal ORDER BY random()" in text
    assert "/ count(*) OVER (PARTITION BY b.band, b.top_signal) AS stratum_position" in text
    assert "PARTITION BY r.band ORDER BY r.stratum_position, random()" in text
    assert "WHERE band_rank <= %(per_band)s" in text
    assert "s.variant = %(variant)s" in text and "NOT EXISTS (SELECT 1 FROM fd.link_sample s" in text


def test_draw_samples_passes_params_and_commits(monkeypatch):
    monkeypatch.setattr(links, "scoring", lambda: THRESHOLDS)
    query_params = {}

    class DrawConn(Conn):
        committed = False

        def commit(self):
            self.committed = True

    conn = DrawConn({"INSERT INTO fd.link_sample": lambda params: query_params.update(params) or [("strong",), ("strong",)]})

    drawn = links.draw_samples(conn, 50, ["strong"])

    assert drawn == {"strong": 2}
    assert conn.committed
    assert query_params == {"certain": 8.0, "strong": 5.0, "variant": "live", "bands": ["strong"], "per_band": 50}


def test_sample_precision_orders_bands_and_maps_weak_target_to_floor():
    targets = {"precision": {"floor": 0.5, "strong": 0.9, "certain": 0.98}}

    samples = links.sample_precision([("weak", 50, 10, 30), ("certain", 50, 4, 0)], targets)

    assert list(samples) == ["certain", "weak"]
    assert samples["weak"] == {"drawn": 50, "right": 10, "wrong": 30, "target": 0.5}
    assert samples["certain"]["target"] == 0.98


def test_render_samples_prints_precision_and_target():
    result = {
        "links": "fd.member_link",
        "bands": {"certain": 1, "strong": 1, "weak": 0},
        "samples": {"strong": {"drawn": 50, "right": 9, "wrong": 1, "target": 0.9},
                    "weak": {"drawn": 50, "right": 0, "wrong": 0, "target": 0.5}},
        "verdicts": {},
        "groups": [],
        "aliases": {"pairs": 0, "linked": 0, "bands": {}},
    }

    text = "\n".join(links.render(result))

    assert "strong     10 labelled of 50   precision 90%, target 90%" in text
    assert "weak        0 labelled of 50   precision n/a, target 50%" in text


def test_render_without_samples_prints_none_drawn():
    result = {"links": "fd.member_link", "bands": {}, "samples": {}, "verdicts": {}, "groups": [],
              "aliases": {"pairs": 0, "linked": 0, "bands": {}}}

    assert "sampled links: none drawn yet (check-links --draw 50)" in links.render(result)


def test_main_draw_with_zero_count_or_shadow_links_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(links, "load_dotenv", lambda *_args: None)
    monkeypatch.setattr(links, "connect", lambda *_args: pytest.fail("connected"))

    assert links.main(["--draw", "0"]) == 2
    assert links.main(["--draw", "50", "--links", "fd.member_link_shadow"]) == 2
    assert "--draw requires a positive count and fd.member_link or a --variant" in capsys.readouterr().err


def test_main_draw_prints_drawn_count_per_band(monkeypatch, capsys):
    class Writable:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr(links, "load_dotenv", lambda *_args: None)
    monkeypatch.setattr(links, "connect", lambda *_args: Writable())
    monkeypatch.setattr(links, "draw_samples",
                        lambda _conn, per_band, bands, variant: {"strong": per_band} if bands == ["strong"] else {})

    assert links.main(["--draw", "50", "--band", "strong"]) == 0
    assert capsys.readouterr().out == "check-links: drew 0 certain, 50 strong, 0 weak into fd.link_sample as live\n"
    assert links.main(["--draw", "50", "--band", "strong", "--variant", "flat_inbox"]) == 0
    assert capsys.readouterr().out.endswith("into fd.link_sample as flat_inbox\n")


def test_links_source_variant_selects_shadow_rows_by_variant():
    source = links.links_source(variant="flat_inbox").as_string(None)

    assert source == '(SELECT * FROM "fd"."member_link_shadow" WHERE variant = \'flat_inbox\')'
    assert links.links_source().as_string(None) == '"fd"."member_link"'
    for name in ("live", "Flat", "a;drop", ""):
        with pytest.raises(ValueError):
            links.links_source(variant=name)


def test_draw_samples_variant_passes_variant_param(monkeypatch):
    monkeypatch.setattr(links, "scoring", lambda: THRESHOLDS)
    query_params = {}

    class DrawConn(Conn):
        def commit(self):
            pass

    conn = DrawConn({"member_link_shadow": lambda params: query_params.update(params) or []})

    links.draw_samples(conn, 10, ["strong"], "flat_inbox")

    assert query_params["variant"] == "flat_inbox"


def test_band_shift_counts_added_dropped_up_down_and_same_links():
    rows = [("certain", None, 3), (None, "weak", 5), ("certain", "strong", 2), ("weak", "strong", 1),
            ("strong", "strong", 9)]

    shift = links.band_shift(rows)

    assert shift["added"] == {"certain": 3}
    assert shift["dropped"] == {"weak": 5}
    assert (shift["up"], shift["down"], shift["same"]) == (2, 1, 9)


def test_render_variant_prints_shift_and_live_recall():
    variant_recall = {"pairs": 4, "found": 3, "bands": {"certain": 3, "not linked": 1}, "signals": {}, "evidence": {}}
    live_recall = {**variant_recall, "found": 2}
    result = {
        "links": "fd.member_link_shadow (flat_inbox)",
        "variant": "flat_inbox",
        "bands": {"certain": 3, "strong": 0, "weak": 0},
        "shift": {"added": {"certain": 3}, "dropped": {"weak": 5}, "up": 2, "down": 1, "same": 9},
        "recall": {"post-ban": variant_recall},
        "baseline": {"post-ban": live_recall},
        "samples": {},
        "verdicts": {},
        "groups": [],
        "aliases": {"pairs": 0, "linked": 0, "bands": {}},
    }

    text = "\n".join(links.render(result))

    assert ("against fd.member_link: 3 added (certain 3, strong 0, weak 0), 5 dropped "
            "(certain 0, strong 0, weak 5), 2 moved up a band, 1 moved down, 9 unchanged") in text
    assert "not linked 1  (live 2 of 4)" in text
    assert "none drawn yet (check-links --draw 50 --variant flat_inbox)" in text


def test_main_variant_with_links_or_live_name_returns_2(monkeypatch, capsys):
    monkeypatch.setattr(links, "load_dotenv", lambda *_args: None)
    monkeypatch.setattr(links, "connect", lambda *_args: pytest.fail("connected"))

    assert links.main(["--variant", "flat_inbox", "--links", "fd.other"]) == 2
    assert links.main(["--variant", "live"]) == 2
    err = capsys.readouterr().err
    assert "--variant reads fd.member_link_shadow, --links not allowed" in err
    assert "'live' is not a variant name" in err
