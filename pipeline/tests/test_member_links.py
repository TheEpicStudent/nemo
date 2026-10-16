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


def test_scoring_thresholds_floor_strong_certain_are_ascending():
    thresholds = links.scoring()
    assert thresholds["floor"] < thresholds["strong"] < thresholds["certain"]


def test_signals_email_domain_and_joined_together_alone_score_below_floor():
    thresholds = links.scoring()
    assert score_for("email_domain", 6) < thresholds["floor"], \
        "six people on one domain is a school, not an alt"
    assert score_for("joined_together", 2) < thresholds["floor"], \
        "arriving together is a crowd signal, not an identity"


def test_member_links_schema_orders_pair_ids_and_keys_by_pair():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0149_member_links.sql").read_text()
    assert "CHECK (a_user_id < b_user_id)" in sql
    assert "PRIMARY KEY (a_user_id, b_user_id)" in sql
    assert "least(a.user_id, b.user_id)" in links.PAIRS_SQL


def test_member_link_verdicts_schema_orders_pair_ids_and_is_unique_per_pair():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0181_member_link_verdicts.sql").read_text()
    assert "CHECK (a_user_id < b_user_id)" in sql
    assert "UNIQUE (a_user_id, b_user_id)" in sql


def test_pairs_and_together_sql_prune_ceiling_before_self_join():
    for sql in (links.PAIRS_SQL, links.TOGETHER_SQL):
        prune_index = sql.index("BETWEEN 2 AND %(ceiling)s")
        join_index = sql.index("JOIN candidate b")
        assert prune_index < join_index, (
            "a value thousands of people share must be dropped before the self-join; "
            "filtering after it materialises n squared rows and the pass never ends")
        assert "FROM candidate a" in sql


def test_pairs_and_together_sql_do_not_join_unpruned_evidence():
    for sql in (links.PAIRS_SQL, links.TOGETHER_SQL):
        assert "FROM ev a" not in sql
        assert "JOIN ev b" not in sql


def test_shared_config_rotates_above_and_min_sightings_thresholds():
    shared_config = links.shared()
    assert shared_config["rotates_above"] > 1, "a carrier hands each person a fresh address every time"
    assert shared_config["min_sightings"] >= 2, "one sighting on an address is a coincidence, not a home"


def test_shared_isp_sql_derives_networks_without_named_isps():
    assert "count(DISTINCT ip)" in links.SHARED_ISP
    assert "count(DISTINCT user_id)" in links.SHARED_ISP
    assert "rotates" in links.SHARED_ISP
    for isp_name in ("T-Mobile", "ProtonVPN", "Jio"):
        assert isp_name not in links.SHARED_ISP, "no isp is named in the code"


def test_shared_isp_and_shared_ip_sql_drop_tables_on_commit():
    assert "ON COMMIT DROP" in links.SHARED_ISP
    assert "ON COMMIT DROP" in links.SHARED_IP


def test_signals_each_family_exists_with_positive_cap():
    caps = links.families()
    for name, definition in links.signals().items():
        assert definition["family"] in caps, name
    for family, definition in caps.items():
        assert definition["cap"] > 0, family


def test_families_only_identity_reaches_certain_threshold_alone():
    certain_threshold = links.scoring()["certain"]
    for family, definition in links.families().items():
        if family != "identity":
            assert definition["cap"] < certain_threshold, family
    assert links.signals()["mailbox_alias"]["weight"] >= certain_threshold


def test_family_table_columns_have_equal_length_and_align_by_signal():
    table = links.family_table(links.catalogue())

    assert len({len(column) for column in table.values()}) == 1
    position = table["signals"].index("session_agent")
    assert table["families"][position] == "device"
    assert table["corroborating"][position] is True


def test_pass_sql_caps_each_family_before_summing_families():
    assert "least(sum(b.score), f.cap)" in links.PASS
    assert "bool_or(NOT corroborating)" in links.PASS


def test_upsert_sql_skips_unchanged_links_and_sweep_checks_link_pass():
    assert "IS DISTINCT FROM" in links.UPSERT_SQL
    assert "NOT EXISTS (SELECT 1 FROM link_pass" in links.SWEEP


def test_sweep_sql_excludes_links_computed_after_pass_start():
    assert "l.computed_at < now()" in links.SWEEP


def test_run_executes_statements_in_order_commits_and_prints_summary(monkeypatch, capsys):
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
    monkeypatch.setattr(links, "load_signal_pairs", lambda _conn, _config, _totals: {"ip_stable": 3})

    assert links.run(Conn()) == 4
    executed[:] = [statement for statement in executed if statement not in ("ANALYZE shared_ip", "ANALYZE link_part", links.SAVE_WHOLES_SQL,
                                                          links.SET_QUIET_LINKS)]
    assert executed[:11] == [links.PASS, links.PASS_INDEX, "ANALYZE link_pass", links.PRESENCE.format(**links.FULL),
                             links.PRESENCE_INDEX,
                             "ANALYZE presence", links.COUNTRY_CONFLICT, links.STAFF_TEST,
                             links.BELOW_FLOOR, links.UPSERT_SQL, links.SWEEP]
    assert executed[-1] == "commit"
    assert "9 link(s) kept, 4 written, 1 dropped" in capsys.readouterr().out


def test_signals_include_class_aware_ip_signals_and_exclude_legacy_ones():
    names = set(links.signals())

    assert {"ip_stable", "ip_same_hour", "ip_many", "ip_hourly", "ip_prefix_stable"} <= names
    assert not {"ip_exact", "ip_prefix"} & names
    assert {"email_domain", "session_agent", "joined_together"} <= names


def test_signals_ip_prefix_stable_is_corroborating():
    assert links.signals()["ip_prefix_stable"]["corroborating"] is True


def test_evidence_returns_sql_per_signal_and_none_for_unknown_signal():
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


def test_sighting_sql_shared_ip_is_classified_rotating():
    assert ("WHEN EXISTS (SELECT 1 FROM shared_ip s WHERE s.ip = e.ip) THEN 'rotating'"
            in links.SIGHTING.format(**links.FULL))


def test_collapsed_signals_insert_one_row_per_pair():
    assert set(links.COLLAPSED) == {"ip_same_hour", "ip_hourly", "ip_burst"}
    assert "DISTINCT ON (a_user_id, b_user_id)" in links.INSERT_COLLAPSED_PART


def test_country_conflict_two_countries_has_negative_weight_and_excludes_vpn_classes():
    assert links.country_conflict_settings()["two_countries"]["weight"] < 0
    assert "s.class NOT IN ('vpn', 'hosting', 'tor')" in links.PRESENCE
    assert "coalesce(e.country, n.country) AS country" in links.SIGHTING
    assert "b.hour = a.hour AND b.country <> a.country" in links.COUNTRY_CONFLICT


def test_presence_and_country_conflict_sql_read_only_candidate_link_members():
    assert "FROM sighting s" in links.PRESENCE.format(**links.FULL)
    assert "SELECT a_user_id FROM link_pass UNION SELECT b_user_id FROM link_pass" in links.PRESENCE
    assert "fd.login_event" not in links.COUNTRY_CONFLICT


def test_signals_device_agent_and_device_ja4_are_corroborating_device_family():
    signals = links.signals()

    assert signals["device_agent"]["family"] == "device"
    assert signals["device_agent"]["corroborating"] is True
    assert signals["device_ja4"]["corroborating"] is True
    assert signals["device_agent"]["crowd_ceiling"] <= 25


def test_evidence_device_agent_and_device_ja4_sql_use_agent_length_and_anomaly_filter():
    signals = links.signals()

    agent, _ = links.evidence("device_agent", signals["device_agent"], 2)
    ja4, _ = links.evidence("device_ja4", signals["device_ja4"], 2)

    assert "u.ua AS value" in agent and f"length(u.ua) >= {links.SHORTEST_AGENT}" in agent
    assert "client_ja4_fingerprint" in ja4 and "action = 'anomaly'" in ja4
    assert "BETWEEN 2 AND %(ceiling)s" in agent


def test_signals_device_agent_weight_and_device_cap_are_below_strong():
    signals = links.signals()
    assert signals["device_agent"]["weight"] < links.scoring()["strong"]
    assert links.families()["device"]["cap"] < links.scoring()["strong"]


def test_families_name_cap_is_below_strong_and_name_signals_use_name_family():
    assert links.families()["name"]["cap"] < links.scoring()["strong"]
    for name in ("full_name", "display_name", "handle_stem"):
        assert links.signals()[name]["family"] == "name"


def test_mailbox_rows_fold_aliases_and_skip_staff_and_invalid_addresses():
    rows = list(links.mailbox_rows([("U1", "Jo.Doe+x@googlemail.com"), ("U2", "x@mail.hackclub.com"),
                                 ("U3", "nope"), ("U4", "kai@school.edu")], ["hackclub.com"]))

    assert rows == [("U1", "jodoe@gmail.com", "jodoe", "gmail.com"),
                    ("U4", "kai@school.edu", "kai", "school.edu")]


def test_evidence_name_signals_exclude_bots_and_deactivated_accounts():
    signals = links.signals()
    for name in ("full_name", "display_name", "handle_stem", "handle_stem_long"):
        sql, _ = links.evidence(name, signals[name], 2)
        assert "NOT" in sql and "is_bot" in sql
        assert "position('deactivateduser' IN lower(" in sql
        assert f">= {links.SHORTEST_NAME}" in sql or f">= {links.SHORTEST_LONG_STEM}" in sql


def test_evidence_handle_stem_strips_trailing_non_letters():
    sql, _ = links.evidence("handle_stem", links.signals()["handle_stem"], 2)
    assert "regexp_replace(lower(handle), '[^a-z]+$', '')" in sql


def test_mailbox_score_links_and_member_links_share_lib_mailbox_function():
    from jobs import score_links
    from lib import mailbox as rule

    assert score_links.mailbox is rule.mailbox
    assert links.mailbox is rule.mailbox


def test_signals_only_after_ban_exit_reaches_strong_in_arrival_family():
    strong = links.scoring()["strong"]
    for name in ("created_same_address", "invited_by", "after_ban_address", "after_ban_device"):
        assert links.signals()[name]["family"] == "arrival"
        assert links.signals()[name]["weight"] < strong
    exit_signal = links.signals()["after_ban_exit"]
    assert exit_signal["family"] == "arrival"
    assert exit_signal["weight"] >= strong
    assert links.families()["arrival"]["cap"] == exit_signal["weight"]


def test_banned_sql_excludes_bans_followed_by_reactivation():
    assert "max(at) FILTER (WHERE action = 'user_reactivated') AS back_at" in links.BANNED
    assert "banned_at > coalesce(back_at, '-infinity'::timestamptz)" in links.BANNED


def test_evidence_after_ban_address_sql_requires_stable_first_sighting_after_ban():
    sql, _ = links.evidence("after_ban_address", links.signals()["after_ban_address"], 2)

    assert "s.class = 'stable' AND s.hour <= h.banned_at" in sql
    assert "a.first_at > u.banned_at" in sql


def test_evidence_invited_by_sql_excludes_creators_over_ceiling():
    sql, args = links.evidence("invited_by", links.signals()["invited_by"], 2)

    assert "action = 'user_created'" in sql
    assert "WHERE c.user_count <= %(ceiling)s" in sql
    assert args["ceiling"] == 20


def test_evidence_created_same_address_sql_requires_same_ip_within_window():
    sql, args = links.evidence("created_same_address", links.signals()["created_same_address"], 2)

    assert "JOIN fd.member_joins j" in sql
    assert "b.ip = a.ip" in sql and "make_interval(secs => %(window)s)" in sql
    assert args["window"] == 1800


def test_labels_match_member_link_by_family_migration():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
           / "0188_member_link_by_family.sql").read_text()
    for name in links.labels():
        assert f"'{name}'" in sql


def test_staff_test_label_has_no_weight_and_staff_test_sql_has_no_score():
    labels = links.labels()

    assert "weight" not in labels["staff_test"]
    assert "score" not in links.STAFF_TEST


def test_staff_members_returns_accounts_with_staff_mailbox():
    rows = list(links.staff_members([("U1", "x+test@mail.hackclub.com"), ("U2", "y@gmail.com"),
                                  ("U3", None)], ["hackclub.com"]))
    assert rows == [("U1",)]


def test_upsert_sql_updates_label_on_conflict():
    assert "label = EXCLUDED.label" in links.UPSERT_SQL
    assert "EXCLUDED.label)" in links.UPSERT_SQL


def test_prepare_and_run_source_analyze_each_temp_table():
    import inspect

    prepare_source = inspect.getsource(links.prepare)
    run_source = inspect.getsource(links.run) + inspect.getsource(links.score_pairs)
    for table in ("sighting", "mailbox", "staff_member"):
        assert f'"ANALYZE {table}"' in prepare_source, table
    for table in ("shared_ip", "link_part", "link_pass"):
        assert f'"ANALYZE {table}"' in run_source, table


def test_pass_sql_groups_signals_by_pair_without_per_pair_lookup():
    assert "FROM best b\n        WHERE b.a_user_id = p.a_user_id" not in links.PASS
    assert "GROUP BY b.a_user_id, b.b_user_id" in links.PASS


def test_signals_mailbox_alias_crowd_ceiling_is_at_least_100():
    assert links.signals()["mailbox_alias"]["crowd_ceiling"] >= 100


def test_signals_device_agent_crowd_ceiling_is_at_most_5():
    assert links.signals()["device_agent"]["crowd_ceiling"] <= 5


def test_signals_name_signals_are_corroborating():
    for name in ("full_name", "display_name", "handle_stem"):
        assert links.signals()[name]["corroborating"] is True, name


def test_signals_handle_stem_long_is_corroborating_name_signal_below_strong_cap():
    signal = links.signals()["handle_stem_long"]
    sql, args = links.evidence("handle_stem_long", signal, 2)

    assert signal["corroborating"] is True
    assert signal["family"] == "name"
    assert f">= {links.SHORTEST_LONG_STEM}" in sql and links.SHORTEST_LONG_STEM >= 8
    assert args["ceiling"] >= 14
    assert signal["weight"] * 0.8 >= links.scoring()["floor"]
    assert links.families()["name"]["cap"] < links.scoring()["strong"]


def test_signals_handle_stem_is_corroborating():
    assert links.signals()["handle_stem"]["corroborating"] is True


def test_signals_ip_hourly_weight_reaches_floor():
    assert links.signals()["ip_hourly"]["weight"] >= links.scoring()["floor"]


def test_signals_non_corroborating_set_matches_primary_signals():
    primary = {name for name, definition in links.signals().items() if not definition.get("corroborating")}

    assert primary == {"ip_stable", "ip_many", "ip_hourly", "ip_burst", "mailbox_alias", "local_part",
                       "created_same_address", "invited_by", "after_ban_exit",
                       "after_ban_address", "after_ban_device"}


def test_evidence_ip_stable_sql_limits_users_per_range_to_20():
    sql, _ = links.evidence("ip_stable", links.signals()["ip_stable"], 2)

    assert "HAVING count(DISTINCT user_id) <= 20" in sql
    assert links.signals()["ip_same_hour"]["corroborating"] is True


def test_evidence_ip_burst_sql_requires_same_exit_browser_and_join_window():
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


def test_evidence_ip_burst_vpn_or_tor_weight_is_strong_and_base_weight_is_lower():
    signal = links.signals()["ip_burst"]
    sql, _args = links.evidence("ip_burst", signal, 2)

    assert "bool_or(n.class IN ('vpn', 'tor')) AS anonymized" in sql
    assert "CASE WHEN a.anonymized THEN %(vpn_weight)s ELSE %(weight)s END::numeric AS score" in sql
    assert signal["vpn_weight"] >= links.scoring()["strong"] > signal["weight"]


def test_repeated_pairs_only_ip_many_with_ip_stable():
    assert links.REPEATED == (("ip_many", "ip_stable"),)


def test_evidence_every_signal_except_ip_many_returns_sql():
    for name, settings in links.signals().items():
        if name == links.IP_MANY:
            continue
        sql, _ = links.evidence(name, settings, 2)
        assert sql is not None, name


def test_upsert_and_sweep_sql_target_member_link_table():
    assert "INSERT INTO fd.member_link\n" in links.UPSERT_SQL
    assert "top_signal = EXCLUDED.top_signal" in links.UPSERT_SQL
    assert "DELETE FROM fd.member_link l" in links.SWEEP


def test_run_and_mark_shared_save_wholes_and_shared_for_live_lane():
    import inspect

    run_source = inspect.getsource(links.run)
    assert "save_wholes(conn, wholes)" in run_source
    assert "SAVE_SHARED_SQL" in inspect.getsource(links.mark_shared)
    assert "rarity(%(whole)s::numeric, k.counted)" in links.RARITY_SCORE
    assert "rarity(%(whole)s::numeric, k.user_count)" in links.TOGETHER_SQL


def test_evidence_live_lane_excludes_over_cap_values_and_full_lane_does_not():
    live_names = {**links.FULL, "over_cap": "over_cap"}
    sql, _ = links.evidence("email_domain", links.signals()["email_domain"], 2, live_names)
    assert "AND value NOT IN (SELECT value FROM over_cap WHERE signal = %(name)s)" in sql
    full, _ = links.evidence("email_domain", links.signals()["email_domain"], 2)
    assert "over_cap" not in full


def test_pass_sql_orders_ties_by_signal_and_family_deterministically():
    assert "ORDER BY b.score DESC, b.signal" in links.PASS
    assert "ORDER BY score DESC, family" in links.PASS
    assert "ORDER BY a_user_id, b_user_id, signal, score DESC, value" in links.PASS
    assert "ORDER BY a_user_id, b_user_id, score DESC, value" in links.INSERT_COLLAPSED_PART


def test_build_shadow_executes_only_shadow_statements_and_returns_row_count(monkeypatch):
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
    monkeypatch.setattr(links, "load_signal_pairs", lambda _conn, _config, _totals: {})

    assert links.build_shadow(Conn(), links.catalogue(), "flat_inbox") == 7
    statements = [sql for sql, _params in executed]
    for live_write in (links.SAVE_SHARED_SQL, links.SAVE_WHOLES_SQL, links.UPSERT_SQL, links.SWEEP, links.SET_QUIET_LINKS):
        assert live_write not in statements
    clear_index = statements.index(links.SHADOW_CLEAR_SQL)
    insert_index = statements.index(links.SHADOW_INSERT_SQL)
    assert clear_index < insert_index < statements.index("commit")
    assert executed[clear_index][1] == executed[insert_index][1] == {"variant": "flat_inbox"}


def test_shadow_insert_sql_includes_every_upsert_column():
    for column in ("score", "top_signal", "top_family", "families", "signals", "first_seen", "last_seen", "label"):
        assert column in links.SHADOW_INSERT_SQL
    assert "INSERT INTO fd.member_link_shadow" in links.SHADOW_INSERT_SQL
    assert "FROM link_pass" in links.SHADOW_INSERT_SQL


def test_evidence_default_signal_uses_rarity_score_without_oldest_pairing():
    sql, _args = links.evidence("device_agent", {"weight": 3.0, "crowd_ceiling": 8}, 2)

    assert links.RARITY_SCORE + " AS score" in sql
    assert "oldest" not in sql


def test_evidence_flat_link_to_oldest_signal_scores_weight_and_pairs_with_oldest():
    settings = {"weight": 8.0, "crowd_ceiling": 100, "rarity_discount": False, "link_to_oldest": True}

    sql, args = links.evidence("mailbox_alias", settings, 2)

    assert "%(weight)s::numeric AS score" in sql and "rarity(" not in sql
    assert "LEFT JOIN fd.member_joins j ON j.user_id = s.user_id" in sql
    assert "ORDER BY s.value, j.joined_at NULLS LAST, s.user_id" in sql
    assert "WHERE o.user_id IN (a.user_id, b.user_id)" in sql
    assert args["ceiling"] == 100


def test_oldest_account_filter_keeps_pairs_with_verdict():
    assert "OR EXISTS (SELECT 1 FROM fd.member_link_verdict v" in links.OLDEST_ACCOUNT_FILTER


def test_evidence_live_lane_link_to_oldest_uses_scope_joins():
    settings = {"weight": 8.0, "crowd_ceiling": 100, "link_to_oldest": True}

    sql, _args = links.evidence("mailbox_alias", settings, 2, live.LIVE)

    assert "LEFT JOIN scope_joins j ON j.user_id = s.user_id" in sql


def test_catalogue_mailbox_alias_is_flat_and_links_to_oldest():
    catalogue_signal = links.catalogue()["identity_signals"]["mailbox_alias"]

    assert (catalogue_signal["rarity_discount"], catalogue_signal["link_to_oldest"]) == (False, True)
    sql, _args = links.evidence("mailbox_alias", catalogue_signal, 2)
    assert "%(weight)s::numeric AS score" in sql and "JOIN oldest_account o ON o.value = a.value" in sql


def test_pass_sql_requires_non_corroborating_signal_per_pair():
    assert "bool_and(f.corroborating) AS corroborating" in links.PASS
    assert "HAVING sum(score) >= %(floor)s AND bool_or(NOT corroborating)" in links.PASS
    table = links.family_table({**links.catalogue(), "name_signals": {
        **links.catalogue()["name_signals"], "handle_stem_long": {"weight": 4.0, "corroborating": True}}})
    assert table["corroborating"][table["signals"].index("handle_stem_long")] is True


def test_evidence_after_ban_exit_sql_requires_staff_ban_small_exit_same_build_and_window():
    signal = links.signals()["after_ban_exit"]
    sql, args = links.evidence("after_ban_exit", signal, 2)

    assert (signal["crowd_ceiling"], signal["window_days"], args["window"]) == (10, 30, 30)
    assert args["bot_user_ids"] == ["USLACKBOT", "U09ULFV88KU"]
    assert "d.actor_id IS DISTINCT FROM d.user_id AND d.actor_id <> ALL(%(bot_user_ids)s)" in sql
    assert "r.action = 'user_reactivated' AND r.entity_id = d.user_id AND r.at > d.banned_at" in sql
    assert "n.class IN ('vpn', 'hosting')" in sql
    assert "SELECT user_id FROM fd.member WHERE NOT is_bot" in sql
    assert "c.user_count <= %(ceiling)s" in sql
    assert "x.ua_id = u.ua_id" in sql
    assert "x.first_at > u.banned_at" in sql
    assert "x.first_at <= u.banned_at + make_interval(days => %(window)s)" in sql


def test_evidence_live_lane_after_ban_exit_reads_scope_tables():
    sql, _args = links.evidence("after_ban_exit", links.signals()["after_ban_exit"], 2, live.LIVE)

    assert "FROM scope_login e" in sql
    assert "FROM scope_audit" in sql
    assert "FROM scope_member WHERE NOT is_bot" in sql


def test_evidence_created_same_address_window_arg_uses_window_seconds():
    _sql, args = links.evidence("created_same_address", links.signals()["created_same_address"], 2)

    assert args["window"] == links.signals()["created_same_address"]["window_seconds"]


def test_shared_isp_sql_has_no_isp_crowd_threshold_and_ip_stable_ceilings_are_8_and_20():
    assert "crowds" not in links.SHARED_ISP
    assert "count(DISTINCT user_id) >=" not in links.SHARED_ISP
    assert "crowds_above" not in links.shared()
    signal = links.signals()["ip_stable"]
    assert (signal["crowd_ceiling"], signal["range_ceiling"]) == (8, 20)


def test_pairs_sql_counts_banned_members_as_one_holder():
    sql = links.PAIRS_SQL

    assert "count(DISTINCT user_id) FILTER (WHERE user_id IN (SELECT user_id FROM banned_member)) AS banned" in sql
    assert "greatest(2, least(user_count, user_count - banned + 1)) AS counted" in sql
    assert "FROM counted WHERE counted BETWEEN 2 AND %(ceiling)s" in sql
    assert "k.counted" in links.RARITY_SCORE


def test_pairs_sql_above_ceiling_value_pairs_only_with_banned_member():
    sql = links.PAIRS_SQL

    assert "user_count > %(ceiling)s AS above_ceiling" in sql
    assert "AND (NOT k.above_ceiling" in sql
    assert "OR a.user_id IN (SELECT user_id FROM banned_member)" in sql
    assert "OR b.user_id IN (SELECT user_id FROM banned_member)" in sql


def test_banned_member_sql_selects_active_staff_bans():
    assert links.BANNED_MEMBER.startswith("\nCREATE TEMP TABLE banned_member ON COMMIT DROP AS")
    assert "d.actor_id IS DISTINCT FROM d.user_id AND d.actor_id <> ALL(%(bot_user_ids)s)" in links.BANNED_MEMBER
    assert links.BANNED_MEMBER.rstrip().endswith("SELECT user_id FROM active_ban")


def test_prepare_live_scope_builds_banned_member_from_scope_audit():
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


def test_evidence_device_ja3_is_corroborating_device_signal_with_weight_1_and_ceiling_25():
    signal = links.signals()["device_ja3"]
    sql, args = links.evidence("device_ja3", signal, 2)

    assert signal["family"] == "device" and signal["corroborating"] is True
    assert (signal["weight"], signal["crowd_ceiling"]) == (1.0, 25)
    assert "payload->'details'->>'client_ja3_fingerprint' AS value" in sql
    assert "FROM slack.audit_event" in sql and "action = 'anomaly'" in sql
    assert args["ceiling"] == 25


def test_evidence_live_lane_device_ja3_excludes_over_cap_values():
    assert "('ja3', 'device_ja3')" in live.OVER_CAP
    sql, _args = links.evidence("device_ja3", links.signals()["device_ja3"], 2, live.LIVE)
    assert "FROM scope_audit" in sql
    assert "value NOT IN (SELECT value FROM over_cap WHERE signal = %(name)s)" in sql


def test_member_trait_ja3_migration_adds_ja3_trait_and_backfills_with_trigger_disabled():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0219_member_trait_ja3.sql").read_text()

    assert "'ip', 'ip_prefix', 'ua_id', 'ja4', 'ja3'," in sql
    assert "('ja3', CASE WHEN NEW.action = 'anomaly' THEN NEW.payload->'details'->>'client_ja3_fingerprint' END)" in sql
    assert "('ja4', CASE WHEN NEW.action = 'anomaly'" in sql and "('inviter', CASE WHEN NEW.action <> 'anomaly'" in sql
    disable_index = sql.index("DISABLE TRIGGER member_trait_touches")
    backfill_index = sql.index("SELECT actor_id, 'ja3'")
    enable_index = sql.index("ENABLE TRIGGER member_trait_touches")
    assert disable_index < backfill_index < enable_index
