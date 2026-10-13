import contextlib
import pathlib

from ingest import member_links as links
from ingest import member_links_live as live

POPULATION = 1000


def rarity(group_size, population=POPULATION):
    import math
    if population <= 2 or group_size <= 1:
        return 1.0
    if group_size >= population:
        return 0.0
    return min(1.0, max(0.0, math.log(population / group_size) / math.log(population / 2)))


def score_for(name, group_size, population=POPULATION):
    return links.signals()[name]["weight"] * rarity(group_size, population)


def test_the_bands_climb():
    thresholds = links.scoring()
    assert thresholds["floor"] < thresholds["strong"] < thresholds["certain"]


def test_a_school_domain_cannot_link_two_people_on_its_own():
    thresholds = links.scoring()
    assert score_for("email_domain", 6) < thresholds["floor"], \
        "six people on one domain is a school, not an alt"
    assert score_for("joined_together", 2) < thresholds["floor"], \
        "arriving together is a crowd signal, not an identity"


def test_a_pair_is_written_one_way_round_so_it_cannot_be_held_twice():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0149_member_links.sql").read_text()
    assert "CHECK (a_user_id < b_user_id)" in sql
    assert "PRIMARY KEY (a_user_id, b_user_id)" in sql
    assert "least(a.user_id, b.user_id)" in links.PAIRS_SQL


def test_a_verdict_is_held_once_per_pair_in_the_same_order_as_its_link():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0181_member_link_verdicts.sql").read_text()
    assert "CHECK (a_user_id < b_user_id)" in sql
    assert "UNIQUE (a_user_id, b_user_id)" in sql


def test_the_crowd_ceiling_prunes_before_the_join_not_after_it():
    for sql in (links.PAIRS_SQL, links.TOGETHER_SQL):
        pruned = sql.index("BETWEEN 2 AND %(ceiling)s")
        joined = sql.index("JOIN small b")
        assert pruned < joined, (
            "a value thousands of people share must be dropped before the self-join; "
            "filtering after it materialises n squared rows and the pass never ends")
        assert "FROM small a" in sql


def test_neither_side_of_the_join_reads_the_unpruned_evidence():
    for sql in (links.PAIRS_SQL, links.TOGETHER_SQL):
        assert "FROM ev a" not in sql
        assert "JOIN ev b" not in sql


def test_a_network_many_people_share_is_not_evidence_of_anything():
    shared_config = links.shared()
    assert shared_config["rotates_above"] > 1, "a carrier hands each person a fresh address every time"
    assert shared_config["min_sightings"] >= 2, "one sighting on an address is a coincidence, not a home"


def test_the_shared_networks_are_worked_out_rather_than_listed_by_hand():
    assert "count(DISTINCT ip)" in links.SHARED_ISP
    assert "count(DISTINCT user_id)" in links.SHARED_ISP
    assert "rotates" in links.SHARED_ISP
    for named in ("T-Mobile", "ProtonVPN", "Jio"):
        assert named not in links.SHARED_ISP, "no isp is named in the code"


def test_the_shared_tables_are_gone_when_the_pass_commits():
    assert "ON COMMIT DROP" in links.SHARED_ISP
    assert "ON COMMIT DROP" in links.SHARED_IP


def test_every_signal_belongs_to_a_family_with_a_cap():
    caps = links.families()
    for name, one in links.signals().items():
        assert one["family"] in caps, name
    for family, one in caps.items():
        assert one["cap"] > 0, family


def test_only_identity_evidence_can_reach_certain_alone():
    certain_threshold = links.scoring()["certain"]
    for family, one in links.families().items():
        if family != "identity":
            assert one["cap"] < certain_threshold, family
    assert links.signals()["mailbox_alias"]["weight"] >= certain_threshold


def test_the_family_table_lines_up_signal_by_signal():
    table = links.family_table(links.catalogue())

    assert len({len(column) for column in table.values()}) == 1
    at = table["signals"].index("session_agent")
    assert table["families"][at] == "device"
    assert table["corroborating"][at] is True


def test_each_family_is_capped_before_the_families_are_added():
    assert "least(sum(b.score), f.cap)" in links.PASS
    assert "bool_or(NOT corroborating)" in links.PASS


def test_an_unchanged_link_is_not_written_again():
    assert "IS DISTINCT FROM" in links.UPSERT_SQL
    assert "NOT EXISTS (SELECT 1 FROM link_pass" in links.SWEEP


def test_the_full_rebuild_never_sweeps_a_link_the_live_lane_wrote_after_it_started():
    assert "l.computed_at < now()" in links.SWEEP


def test_a_pass_gathers_once_then_lands_sweeps_and_counts(monkeypatch, capsys):
    executed = []

    class Counts:
        rows_in = 0
        rows_rejected = 0

    class Cursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, _params=None):
            executed.append(sql)
            self.rowcount = {links.UPSERT_SQL: 4, links.SWEEP: 1}.get(sql, 0)

        def fetchone(self):
            return (9,)

    class Conn:
        def cursor(self):
            return Cursor()

        def execute(self, sql, _params=None):
            executed.append(sql)

        def commit(self):
            executed.append("commit")

    @contextlib.contextmanager
    def fake_ingest_run(*_args, **_kwargs):
        yield Counts()

    monkeypatch.setattr(links, "ingest_run", fake_ingest_run)
    monkeypatch.setattr(links, "mark_shared", lambda _conn, _config: 2)
    monkeypatch.setattr(links, "prepare", lambda _conn, _config: None)
    monkeypatch.setattr(links, "measure", lambda _conn, _config: {"ip_stable": 40})
    monkeypatch.setattr(links, "gather", lambda _conn, _config, _totals: {"ip_stable": 3})

    assert links.run(Conn()) == 4
    executed[:] = [one for one in executed if one not in ("ANALYZE shared_ip", "ANALYZE link_part", links.SAVE_WHOLES_SQL,
                                                          links.QUIET)]
    assert executed[:13] == [links.PASS, links.PASS_INDEX, "ANALYZE link_pass", links.PRESENCE.format(**links.FULL),
                             links.PRESENCE_INDEX,
                             "ANALYZE presence", links.AGAINST, links.STAFF_TEST, links.CLASSROOM, links.HOUSEHOLD,
                             links.BELOW_FLOOR, links.UPSERT_SQL, links.SWEEP]
    assert executed[-1] == "commit"
    assert "9 link(s) kept, 4 written, 1 dropped" in capsys.readouterr().out


def test_the_new_finder_takes_its_network_evidence_from_the_class_aware_signals():
    names = set(links.signals())

    assert {"ip_stable", "ip_same_hour", "ip_many", "ip_hourly", "ip_prefix_stable"} <= names
    assert not {"ip_exact", "ip_prefix"} & names
    assert {"email_domain", "session_agent", "joined_together"} <= names


def test_a_home_range_only_counts_alongside_another_family():
    assert links.signals()["ip_prefix_stable"]["corroborating"] is True


def test_each_signal_reads_the_evidence_built_for_it():
    signals = links.signals()

    stable, _ = links.evidence("ip_stable", signals["ip_stable"], 2)
    hourly, _ = links.evidence("ip_hourly", signals["ip_hourly"], 2)
    domain, _ = links.evidence("email_domain", signals["email_domain"], 2)
    together, args = links.evidence("joined_together", signals["joined_together"], 2)

    assert "FROM sighting" in stable and "class = 'stable'" in stable
    assert "HAVING sum(s.seen) >= 2" in stable
    assert "'rotating', 'vpn', 'hosting', 'tor'" in hourly and "md5(u.ua)" in hourly
    assert "fd.member_identity" in domain
    assert together == links.TOGETHER_SQL.format(**links.FULL) and args["window"] == 300
    assert links.evidence("nothing", {"weight": 1, "crowd_ceiling": 2}, 2) == (None, None)


def test_an_address_another_isp_rotates_through_is_treated_as_rotating():
    assert ("WHEN EXISTS (SELECT 1 FROM shared_ip s WHERE s.ip = e.ip) THEN 'rotating'"
            in links.SIGHTING.format(**links.FULL))


def test_hourly_evidence_keeps_one_row_per_pair():
    assert set(links.COLLAPSED) == {"ip_same_hour", "ip_hourly", "ip_burst"}
    assert "DISTINCT ON (a_user_id, b_user_id)" in links.COLLAPSED_PART


def test_two_countries_in_one_hour_count_against_a_link_unless_one_is_a_vpn():
    assert links.against()["two_countries"]["weight"] < 0
    assert "s.class NOT IN ('vpn', 'hosting', 'tor')" in links.PRESENCE
    assert "coalesce(e.country, n.country) AS country" in links.SIGHTING
    assert "b.hour = a.hour AND b.country <> a.country" in links.AGAINST


def test_the_country_check_reads_only_the_members_of_candidate_links():
    assert "FROM sighting s" in links.PRESENCE.format(**links.FULL)
    assert "SELECT a_user_id FROM link_pass UNION SELECT b_user_id FROM link_pass" in links.PRESENCE
    assert "fd.login_event" not in links.AGAINST


def test_a_word_for_word_build_is_device_evidence_and_ja4_only_backs_it_up():
    signals = links.signals()

    assert signals["device_agent"]["family"] == "device"
    assert signals["device_agent"]["corroborating"] is True
    assert signals["device_ja4"]["corroborating"] is True
    assert signals["device_agent"]["crowd_ceiling"] <= 25


def test_device_evidence_reads_the_full_agent_and_the_anomaly_fingerprint():
    signals = links.signals()

    agent, _ = links.evidence("device_agent", signals["device_agent"], 2)
    ja4, _ = links.evidence("device_ja4", signals["device_ja4"], 2)

    assert "u.ua AS value" in agent and f"length(u.ua) >= {links.SHORTEST_AGENT}" in agent
    assert "client_ja4_fingerprint" in ja4 and "action = 'anomaly'" in ja4
    assert "BETWEEN 2 AND %(ceiling)s" in agent


def test_a_shared_build_alone_stays_below_strong():
    signals = links.signals()
    assert signals["device_agent"]["weight"] < links.scoring()["strong"]
    assert links.families()["device"]["cap"] < links.scoring()["strong"]


def test_a_name_alone_stays_below_strong():
    assert links.families()["name"]["cap"] < links.scoring()["strong"]
    for name in ("full_name", "display_name", "handle_stem"):
        assert links.signals()[name]["family"] == "name"


def test_mailboxes_fold_aliases_and_leave_out_staff_domains():
    rows = list(links.mailbox_rows([("U1", "Jo.Doe+x@googlemail.com"), ("U2", "x@mail.hackclub.com"),
                                 ("U3", "nope"), ("U4", "kai@school.edu")], ["hackclub.com"]))

    assert rows == [("U1", "jodoe@gmail.com", "jodoe", "gmail.com"),
                    ("U4", "kai@school.edu", "kai", "school.edu")]


def test_names_skip_bots_and_renamed_deactivated_accounts():
    signals = links.signals()
    for name in ("full_name", "display_name", "handle_stem", "handle_stem_long"):
        sql, _ = links.evidence(name, signals[name], 2)
        assert "NOT" in sql and "is_bot" in sql
        assert "position('deactivateduser' IN lower(" in sql
        assert f">= {links.SHORTEST_NAME}" in sql or f">= {links.SHORTEST_LONG_STEM}" in sql


def test_a_handle_stem_drops_trailing_numbers_and_marks():
    sql, _ = links.evidence("handle_stem", links.signals()["handle_stem"], 2)
    assert "regexp_replace(lower(handle), '[^a-z]+$', '')" in sql


def test_the_harness_and_the_finder_share_one_mailbox_rule():
    from jobs import score_links
    from lib import mailbox as rule

    assert score_links.mailbox is rule.mailbox
    assert links.mailbox is rule.mailbox


def test_only_a_post_ban_vpn_exit_makes_a_strong_link_from_arrival_evidence_alone():
    strong = links.scoring()["strong"]
    for name in ("created_same_address", "invited_by", "after_ban_address", "after_ban_device"):
        assert links.signals()[name]["family"] == "arrival"
        assert links.signals()[name]["weight"] < strong
    exit_signal = links.signals()["after_ban_exit"]
    assert exit_signal["family"] == "arrival"
    assert exit_signal["weight"] >= strong
    assert links.families()["arrival"]["cap"] == exit_signal["weight"]


def test_a_ban_counts_only_while_the_account_stays_deactivated():
    assert "max(at) FILTER (WHERE action = 'user_reactivated') AS back_at" in links.BANNED
    assert "banned_at > coalesce(back_at, '-infinity'::timestamptz)" in links.BANNED


def test_after_a_ban_only_a_first_sighting_counts_and_only_on_a_home_address():
    sql, _ = links.evidence("after_ban_address", links.signals()["after_ban_address"], 2)

    assert "s.class = 'stable' AND s.hour <= h.banned_at" in sql
    assert "a.first_at > u.banned_at" in sql


def test_onboarding_accounts_that_create_everyone_are_not_inviters():
    sql, args = links.evidence("invited_by", links.signals()["invited_by"], 2)

    assert "action = 'user_created'" in sql
    assert "WHERE c.people <= %(ceiling)s" in sql
    assert args["ceiling"] == 20


def test_joining_together_needs_the_same_address_within_the_window():
    sql, args = links.evidence("created_same_address", links.signals()["created_same_address"], 2)

    assert "JOIN fd.member_joins j" in sql
    assert "b.ip = a.ip" in sql and "make_interval(secs => %(window)s)" in sql
    assert args["window"] == 1800


def test_the_labels_match_the_table_check():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
           / "0188_member_link_by_family.sql").read_text()
    for name in links.labels():
        assert f"'{name}'" in sql


def test_household_and_classroom_lower_the_score_and_staff_test_only_labels():
    labels = links.labels()

    assert labels["household"]["weight"] < 0
    assert labels["classroom"]["weight"] < 0
    assert "weight" not in labels["staff_test"]
    assert "score" not in links.STAFF_TEST


def test_a_word_list_becomes_one_pattern_and_an_empty_one_matches_nothing():
    assert links.pattern(["school", "k12"]) == "(school|k12)"
    assert links.pattern([]) == "a^"


def test_staff_members_are_the_accounts_with_a_staff_mailbox():
    rows = list(links.staff_members([("U1", "x+test@mail.hackclub.com"), ("U2", "y@gmail.com"),
                                  ("U3", None)], ["hackclub.com"]))
    assert rows == [("U1",)]


def test_a_household_needs_one_home_line_a_shared_surname_and_two_first_names():
    assert "p.signals ? 'ip_stable'" in links.HOUSEHOLD
    assert "'^.*[[:space:]]'" in links.HOUSEHOLD
    assert "split_part(lower(btrim(a.real_name)), ' ', 1) <>" in links.HOUSEHOLD


def test_a_label_change_is_written_like_any_other_change():
    assert "label = EXCLUDED.label" in links.UPSERT_SQL
    assert "EXCLUDED.label)" in links.UPSERT_SQL


def test_every_temp_table_is_analysed_before_it_is_joined():
    import inspect

    prepared = inspect.getsource(links.prepare)
    passed = inspect.getsource(links.run) + inspect.getsource(links.settle)
    for table in ("sighting", "mailbox", "staff_member"):
        assert f'"ANALYZE {table}"' in prepared, table
    for table in ("shared_ip", "link_part", "link_pass"):
        assert f'"ANALYZE {table}"' in passed, table


def test_signals_are_grouped_by_pair_not_looked_up_per_pair():
    assert "FROM best b\n        WHERE b.a_user_id = p.a_user_id" not in links.PASS
    assert "GROUP BY b.a_user_id, b.b_user_id" in links.PASS


def test_a_shared_inbox_counts_however_many_accounts_use_it():
    assert links.signals()["mailbox_alias"]["crowd_ceiling"] >= 100


def test_a_device_build_counts_only_when_few_members_use_it():
    assert links.signals()["device_agent"]["crowd_ceiling"] <= 5


def test_a_shared_name_only_backs_other_evidence_up():
    for name in ("full_name", "display_name", "handle_stem"):
        assert links.signals()[name]["corroborating"] is True, name


def test_a_long_shared_handle_stem_adds_weight_but_never_links_on_its_own():
    signal = links.signals()["handle_stem_long"]
    sql, args = links.evidence("handle_stem_long", signal, 2)

    assert signal["corroborating"] is True
    assert signal["family"] == "name"
    assert f">= {links.SHORTEST_LONG_STEM}" in sql and links.SHORTEST_LONG_STEM >= 8
    assert args["ceiling"] >= 14
    assert signal["weight"] * 0.8 >= links.scoring()["floor"]
    assert links.families()["name"]["cap"] < links.scoring()["strong"]


def test_a_short_stem_still_only_backs_other_evidence_up():
    assert links.signals()["handle_stem"]["corroborating"] is True


def test_a_vpn_or_mobile_address_in_the_same_hour_with_the_same_browser_reaches_the_floor():
    assert links.signals()["ip_hourly"]["weight"] >= links.scoring()["floor"]


def test_only_precise_evidence_can_make_a_link_on_its_own():
    primary = {name for name, one in links.signals().items() if not one.get("corroborating")}

    assert primary == {"ip_stable", "ip_many", "ip_hourly", "ip_burst", "mailbox_alias", "local_part",
                       "created_same_address", "invited_by", "after_ban_exit",
                       "after_ban_address", "after_ban_device"}


def test_a_home_address_on_a_busy_range_does_not_count():
    sql, _ = links.evidence("ip_stable", links.signals()["ip_stable"], 2)

    assert "HAVING count(DISTINCT user_id) <= 20" in sql
    assert links.signals()["ip_same_hour"]["corroborating"] is True


def test_a_burst_needs_the_same_exit_hour_and_browser_and_joins_in_the_same_week():
    signal = links.signals()["ip_burst"]
    sql, args = links.evidence("ip_burst", signal, 2)

    assert sql == links.BURST.format(**links.names_for(links.FULL, signal, 2))
    assert "JOIN fd.member_joins j" in sql
    assert "make_interval(days => %(window)s)" in sql
    assert "md5(u.ua)" in sql and "'rotating', 'vpn', 'hosting', 'tor'" in sql
    assert args == {"weight": signal["weight"], "vpn_weight": signal["vpn_weight"], "ceiling": 8, "window": 7}
    assert "{" not in sql
    assert signal["weight"] >= links.scoring()["floor"]
    assert "ip_burst" in links.COLLAPSED


def test_a_burst_on_a_vpn_or_tor_exit_is_strong_and_elsewhere_stays_weak():
    signal = links.signals()["ip_burst"]
    sql, _args = links.evidence("ip_burst", signal, 2)

    assert "bool_or(n.class IN ('vpn', 'tor')) AS anonymized" in sql
    assert "CASE WHEN a.anonymized THEN %(vpn_weight)s ELSE %(weight)s END::numeric AS score" in sql
    assert signal["vpn_weight"] >= links.scoring()["strong"] > signal["weight"]


def test_only_home_addresses_earn_the_repeat_bonus():
    assert links.REPEATED == (("ip_many", "ip_stable"),)


def test_every_signal_has_evidence_built_for_it():
    for name, settings in links.signals().items():
        if name == links.IP_MANY:
            continue
        sql, _ = links.evidence(name, settings, 2)
        assert sql is not None, name


def test_the_finder_writes_the_links_table_the_web_reads():
    assert "INSERT INTO fd.member_link\n" in links.UPSERT_SQL
    assert "top_signal = EXCLUDED.top_signal" in links.UPSERT_SQL
    assert "DELETE FROM fd.member_link l" in links.SWEEP


def test_the_full_rebuild_keeps_what_the_live_lane_needs():
    import inspect

    passed = inspect.getsource(links.run)
    assert "save_wholes(conn, wholes)" in passed
    assert "SAVE_SHARED_SQL" in inspect.getsource(links.mark_shared)
    assert "rarity(%(whole)s::numeric, k.counted)" in links.RARITY_SCORE
    assert "rarity(%(whole)s::numeric, k.people)" in links.TOGETHER_SQL


def test_a_value_too_crowded_to_load_never_pairs_in_the_live_lane():
    live = {**links.FULL, "crowded": "crowded"}
    sql, _ = links.evidence("email_domain", links.signals()["email_domain"], 2, live)
    assert "AND value NOT IN (SELECT value FROM crowded WHERE signal = %(name)s)" in sql
    full, _ = links.evidence("email_domain", links.signals()["email_domain"], 2)
    assert "crowded" not in full


def test_ties_break_by_name_so_a_rebuild_does_not_rewrite_unchanged_links():
    assert "ORDER BY b.score DESC, b.signal" in links.PASS
    assert "ORDER BY score DESC, family" in links.PASS
    assert "ORDER BY a_user_id, b_user_id, signal, score DESC, value" in links.PASS
    assert "ORDER BY a_user_id, b_user_id, score DESC, value" in links.COLLAPSED_PART


def test_a_shadow_build_writes_only_its_variant_and_leaves_live_tables_alone(monkeypatch):
    executed = []

    class Cursor:
        rowcount = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def execute(self, sql, params=None):
            executed.append((sql, params))

        def fetchone(self):
            return (7,)

    class Conn:
        def cursor(self):
            return Cursor()

        def execute(self, sql, params=None):
            executed.append((sql, params))
            return self

        def fetchone(self):
            return (0,)

        def commit(self):
            executed.append(("commit", None))

    monkeypatch.setattr(links, "prepare", lambda _conn, _config: None)
    monkeypatch.setattr(links, "measure", lambda _conn, _config: {"ip_stable": 40})
    monkeypatch.setattr(links, "gather", lambda _conn, _config, _totals: {})

    assert links.build_shadow(Conn(), links.catalogue(), "flat_inbox") == 7
    statements = [sql for sql, _params in executed]
    for live_write in (links.SAVE_SHARED_SQL, links.SAVE_WHOLES_SQL, links.UPSERT_SQL, links.SWEEP, links.QUIET):
        assert live_write not in statements
    clear = statements.index(links.SHADOW_CLEAR_SQL)
    insert = statements.index(links.SHADOW_INSERT_SQL)
    assert clear < insert < statements.index("commit")
    assert executed[clear][1] == executed[insert][1] == {"variant": "flat_inbox"}


def test_the_shadow_insert_copies_every_column_the_live_upsert_writes():
    for column in ("score", "top_signal", "top_family", "families", "signals", "first_seen", "last_seen", "label"):
        assert column in links.SHADOW_INSERT_SQL
    assert "INSERT INTO fd.member_link_shadow" in links.SHADOW_INSERT_SQL
    assert "FROM link_pass" in links.SHADOW_INSERT_SQL


def test_a_signal_keeps_its_rarity_discount_and_every_pair_by_default():
    sql, _args = links.evidence("device_agent", {"weight": 3.0, "crowd_ceiling": 8}, 2)

    assert links.RARITY_SCORE + " AS score" in sql
    assert "oldest" not in sql


def test_a_flat_star_inbox_scores_its_weight_and_pairs_each_account_with_the_oldest():
    settings = {"weight": 8.0, "crowd_ceiling": 100, "rarity_discount": False, "link_to_oldest": True}

    sql, args = links.evidence("mailbox_alias", settings, 2)

    assert "%(weight)s::numeric AS score" in sql and "rarity(" not in sql
    assert "LEFT JOIN fd.member_joins j ON j.user_id = s.user_id" in sql
    assert "ORDER BY s.value, j.joined_at NULLS LAST, s.user_id" in sql
    assert "WHERE o.user_id IN (a.user_id, b.user_id)" in sql
    assert args["ceiling"] == 100


def test_a_star_keeps_a_pair_that_has_a_verdict():
    assert "OR EXISTS (SELECT 1 FROM fd.member_link_verdict v" in links.STAR_FILTER


def test_the_live_lane_finds_the_oldest_holder_among_its_scoped_joins():
    settings = {"weight": 8.0, "crowd_ceiling": 100, "link_to_oldest": True}

    sql, _args = links.evidence("mailbox_alias", settings, 2, live.LIVE)

    assert "LEFT JOIN scope_joins j ON j.user_id = s.user_id" in sql


def test_a_shared_inbox_scores_flat_and_links_each_account_to_the_oldest():
    shipped = links.catalogue()["identity_signals"]["mailbox_alias"]

    assert (shipped["rarity_discount"], shipped["link_to_oldest"]) == (False, True)
    sql, _args = links.evidence("mailbox_alias", shipped, 2)
    assert "%(weight)s::numeric AS score" in sql and "JOIN oldest o ON o.value = a.value" in sql


def test_a_pair_needs_one_signal_that_is_not_corroborating():
    assert "bool_and(f.corroborating) AS corroborating" in links.PASS
    assert "HAVING sum(score) >= %(floor)s AND bool_or(NOT corroborating)" in links.PASS
    table = links.family_table({**links.catalogue(), "name_signals": {
        **links.catalogue()["name_signals"], "handle_stem_long": {"weight": 4.0, "corroborating": True}}})
    assert table["corroborating"][table["signals"].index("handle_stem_long")] is True


def test_a_post_ban_vpn_exit_needs_a_staff_ban_a_small_exit_the_same_build_and_thirty_days():
    signal = links.signals()["after_ban_exit"]
    sql, args = links.evidence("after_ban_exit", signal, 2)

    assert (signal["crowd_ceiling"], signal["window_days"], args["window"]) == (10, 30, 30)
    assert args["bot_user_ids"] == ["USLACKBOT", "U09ULFV88KU"]
    assert "d.actor_id IS DISTINCT FROM d.user_id AND d.actor_id <> ALL(%(bot_user_ids)s)" in sql
    assert "r.action = 'user_reactivated' AND r.entity_id = d.user_id AND r.at > d.banned_at" in sql
    assert "n.class IN ('vpn', 'hosting')" in sql
    assert "SELECT user_id FROM fd.member WHERE NOT is_bot" in sql
    assert "c.people <= %(ceiling)s" in sql
    assert "x.ua_id = u.ua_id" in sql
    assert "x.first_at > u.banned_at" in sql
    assert "x.first_at <= u.banned_at + make_interval(days => %(window)s)" in sql


def test_the_live_lane_reads_post_ban_exits_from_its_scope():
    sql, _args = links.evidence("after_ban_exit", links.signals()["after_ban_exit"], 2, live.LIVE)

    assert "FROM scope_login e" in sql
    assert "FROM scope_audit" in sql
    assert "FROM scope_member WHERE NOT is_bot" in sql


def test_other_arrival_signals_keep_their_window_in_seconds():
    _sql, args = links.evidence("created_same_address", links.signals()["created_same_address"], 2)

    assert args["window"] == links.signals()["created_same_address"]["window_seconds"]


def test_a_home_address_is_judged_by_its_own_crowd_not_by_how_big_its_isp_is():
    assert "crowds" not in links.SHARED_ISP
    assert "count(DISTINCT user_id) >=" not in links.SHARED_ISP
    assert "crowds_above" not in links.shared()
    signal = links.signals()["ip_stable"]
    assert (signal["crowd_ceiling"], signal["range_ceiling"]) == (8, 20)


def test_a_ring_of_banned_accounts_counts_as_one_holder():
    sql = links.PAIRS_SQL

    assert "count(DISTINCT user_id) FILTER (WHERE user_id IN (SELECT user_id FROM banned_member)) AS banned" in sql
    assert "greatest(2, least(people, people - banned + 1)) AS counted" in sql
    assert "FROM counted WHERE counted BETWEEN 2 AND %(ceiling)s" in sql
    assert "k.counted" in links.RARITY_SCORE


def test_a_value_under_its_ceiling_only_through_its_ring_links_pairs_with_a_banned_side():
    sql = links.PAIRS_SQL

    assert "people > %(ceiling)s AS ring_only" in sql
    assert "AND (NOT k.ring_only" in sql
    assert "OR a.user_id IN (SELECT user_id FROM banned_member)" in sql
    assert "OR b.user_id IN (SELECT user_id FROM banned_member)" in sql


def test_banned_members_are_the_staff_bans_still_in_force():
    assert links.BANNED_MEMBER.startswith("\nCREATE TEMP TABLE banned_member ON COMMIT DROP AS")
    assert "d.actor_id IS DISTINCT FROM d.user_id AND d.actor_id <> ALL(%(bot_user_ids)s)" in links.BANNED_MEMBER
    assert links.BANNED_MEMBER.rstrip().endswith("SELECT user_id FROM held")


def test_prepare_builds_the_banned_members_from_its_own_audit_source():
    executed = []

    class Conn:
        def execute(self, sql, params=None):
            executed.append((sql, params))
            return self

        def fetchall(self):
            return []

        def cursor(self):
            return self

        def copy(self, *_args):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def write_row(self, _row):
            pass

    links.prepare(Conn(), links.catalogue(), live.LIVE)
    banned = [(sql, params) for sql, params in executed if "banned_member ON COMMIT DROP" in sql]
    assert len(banned) == 1 and "FROM scope_audit" in banned[0][0]
    assert banned[0][1] == {"bot_user_ids": ["USLACKBOT", "U09ULFV88KU"]}
