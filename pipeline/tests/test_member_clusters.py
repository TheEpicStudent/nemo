import contextlib
from datetime import UTC, datetime, timedelta

from ingest import member_clusters as clusters
from lib.graph import components

RULE = {"min_accounts": 4, "window_minutes": 60}


def at(minute, hour=10):
    return datetime(2026, 10, 2, hour, 0, tzinfo=UTC) + timedelta(minutes=minute)


def test_components_chained_pairs_join_largest_first():
    assert components([("U1", "U2"), ("U3", "U2"), ("U7", "U8")]) == [{"U1", "U2", "U3"}, {"U7", "U8"}]


def test_peak_joins_in_window_returns_most_accounts_in_one_window():
    window = timedelta(minutes=60)

    assert clusters.peak_joins_in_window([at(0), at(10), at(50), at(55), at(200)], window) == 4
    assert clusters.peak_joins_in_window([at(0), at(100), at(200)], window) == 1
    assert clusters.peak_joins_in_window([None, at(5), None], window) == 1
    assert clusters.peak_joins_in_window([], window) == 0


def test_oldest_account_returns_earliest_joined_user():
    joined = {"U9": at(30), "U2": at(0), "U5": None}

    assert clusters.oldest_account({"U9", "U2", "U5"}, joined) == "U2"
    assert clusters.oldest_account({"U5", "U4"}, {}) == "U4"


def test_cluster_rows_four_joins_within_hour_marks_burst_and_active():
    group = {"U1", "U2", "U3", "U4"}
    accounts = {"U1": (False, at(0)), "U2": (True, at(5)), "U3": (False, at(20)), "U4": (False, at(40))}

    rows = clusters.cluster_rows([group], accounts, RULE)

    assert {row[1] for row in rows} == {"U1"}
    assert all(row[2] == 4 and row[3] and not row[5] for row in rows)
    assert [row[0] for row in rows if row[4]] == ["U2"]


def test_cluster_rows_joins_spread_over_days_is_not_burst():
    group = {"U1", "U2", "U3", "U4"}
    accounts = {one: (True, at(0, hour)) for one, hour in zip(sorted(group), (1, 5, 9, 13), strict=True)}

    rows = clusters.cluster_rows([group], accounts, RULE)

    assert not any(row[3] for row in rows)


def test_edges_sql_uses_certain_score_or_strong_edge_from_two_families():
    sql = clusters.EDGES_SQL

    assert clusters.settings()["edge_score"] >= 5.0
    assert "l.score >= %(certain)s" in sql
    assert "OR (l.score >= %(edge)s" in sql
    assert "WHERE f.key = ANY(%(families)s) AND f.value::numeric > 0) >= %(strong_families)s" in sql
    assert clusters.STRONG_EDGE_FAMILIES == 2
    assert set(clusters.SIGNAL_FAMILIES) == {"network", "device", "identity", "name", "arrival"}


def test_run_passes_certain_score_and_signal_families_to_edges_query(monkeypatch):
    edge_params = {}

    class Conn:
        rowcount = 0

        def execute(self, sql, params=None):
            if sql == clusters.EDGES_SQL:
                edge_params.update(params)
            return self

        def fetchall(self):
            return []

        def cursor(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def commit(self):
            pass

    @contextlib.contextmanager
    def fake_ingest_run(*_args, **_kwargs):
        yield type("Counts", (), {"rows_in": 0})()

    monkeypatch.setattr(clusters, "ingest_run", fake_ingest_run)
    clusters.run(Conn())

    assert edge_params["certain"] == clusters.links.scoring()["certain"]
    assert edge_params["families"] == ["network", "device", "identity", "name", "arrival"]
    assert edge_params["strong_families"] == 2


def test_upsert_sql_skips_unchanged_rows_and_sweep_deletes_absent_users():
    assert "IS DISTINCT FROM" in clusters.UPSERT_SQL
    assert clusters.SWEEP.startswith("DELETE FROM fd.member_cluster WHERE NOT (user_id = ANY")


def test_edges_sql_same_person_verdict_adds_edge_different_people_removes_link():
    sql = clusters.EDGES_SQL

    assert "UNION\nSELECT a_user_id, b_user_id FROM fd.member_link_verdict WHERE verdict = ANY(%(together)s)" in sql
    assert "v.verdict = ANY(%(apart)s)" in sql
    assert set(clusters.SAME_PERSON_VERDICTS) == {"same_person", "allowed_alt"}
    assert set(clusters.DIFFERENT_PEOPLE_VERDICTS) == {"different_people"}


def test_components_bridging_pair_merges_groups():
    groups = components([("U1", "U2"), ("U3", "U4"), ("U2", "U3")])

    assert groups == [{"U1", "U2", "U3", "U4"}]


def test_cluster_rows_different_people_pair_in_group_sets_conflict():
    accounts = {one: (True, at(i)) for i, one in enumerate(["U1", "U2", "U3"])}

    flagged = clusters.cluster_rows([{"U1", "U2", "U3"}], accounts, RULE, apart=[("U1", "U3")])
    unflagged = clusters.cluster_rows([{"U1", "U2", "U3"}], accounts, RULE, apart=[("U1", "U9")])

    assert all(row[5] for row in flagged)
    assert not any(row[5] for row in unflagged)


def test_upsert_sql_updates_conflict_column():
    assert "conflict = EXCLUDED.conflict" in clusters.UPSERT_SQL
    assert "EXCLUDED.conflict)" in clusters.UPSERT_SQL
