from ingest import member_links as links
from ingest import member_links_live as live


def test_a_value_held_by_more_than_any_ceiling_is_never_loaded():
    ceilings = [one.get("crowd_ceiling", 0) for one in links.signals().values()]
    assert live.CAP > max(ceilings)


def test_every_touched_member_brings_the_co_holders_whose_pairs_it_can_change():
    assert "WHERE v.people <= %(cap)s" in live.RESCORED
    assert "FROM touched_session s" in live.RESCORED
    assert "kind = 'inviter'" in live.RESCORED


def test_network_evidence_reads_whole_ranges_so_every_crowd_is_exact():
    assert "e.ip_prefix IN (SELECT ip_prefix FROM scope_prefix)" in live.SCOPE_LOGIN
    assert "e.ip_prefix NOT IN (SELECT ip_prefix FROM scope_prefix)" in live.SCOPE_LOGIN


def test_the_live_lane_reads_the_stored_shared_networks_and_whole_counts():
    assert live.LIVE["shared_ip"] == "fd.shared_ip"
    assert live.LIVE["crowded"] == "crowded"
    assert "fd.shared_ip" in live.LIVE["sighting"]


def test_the_country_check_reads_every_row_of_the_members_of_a_live_pair():
    assert "FROM fd.login_event WHERE user_id IN (SELECT a_user_id FROM link_pass" in live.LIVE["sighting"]


def test_only_pairs_with_a_rescored_member_are_written_or_swept():
    assert "a_user_id NOT IN (SELECT user_id FROM rescored)" in live.ONLY_RESCORED
    assert "l.a_user_id IN (SELECT user_id FROM rescored) OR l.b_user_id IN" in live.SWEEP


def test_a_member_touched_again_mid_pass_stays_queued():
    assert "t.touched_at = done.touched_at" in live.DONE_SQL


def test_the_lane_measures_missing_totals_instead_of_waiting_for_a_rebuild(monkeypatch, capsys):
    ran = []

    class Conn:
        def execute(self, sql, _args=None):
            ran.append(sql)
            return self

        def fetchall(self):
            return []

        def fetchone(self):
            return (40,)

        def commit(self):
            ran.append("COMMIT")

    monkeypatch.setattr(live.links, "load_mailboxes", lambda _conn, _held, _sources: ran.append("MAILBOXES"))

    assert live.run(Conn()) == 0
    assert "without a full rebuild" in capsys.readouterr().out
    assert any("CREATE TEMP TABLE sighting" in sql and "fd.shared_ip" in sql for sql in ran)
    assert "MAILBOXES" in ran
    assert ran.index(live.links.KEEP_WHOLE) < ran.index("COMMIT") < ran.index(live.TOUCHED_SQL)


def test_measuring_reads_whole_tables_and_the_stored_shared_networks():
    assert live.MEASURED["login"] == "fd.login_event"
    assert live.MEASURED["identity"] == "fd.member_identity"
    assert live.MEASURED["shared_ip"] == "fd.shared_ip"


def test_only_the_missing_totals_are_measured():
    class Conn:
        def __init__(self):
            self.ran = []

        def execute(self, sql, _args=None):
            self.ran.append(sql)
            return self

        def fetchone(self):
            return (40,)

    conn = Conn()
    found = links.measure(conn, links.catalogue(), live.MEASURED, ["device_agent"])
    assert found == {"device_agent": 40}
    assert len(conn.ran) == 1


def test_trait_changes_joins_and_bans_queue_the_member():
    import pathlib

    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0199_live_links.sql").read_text()
    assert "AFTER INSERT OR UPDATE OR DELETE ON fd.member_trait" in sql
    assert "AFTER INSERT OR UPDATE OF joined_at ON fd.member_joins" in sql
    assert "WHEN (NEW.action IN ('user_deactivated', 'user_reactivated'))" in sql
    assert "ON CONFLICT (user_id) DO UPDATE SET touched_at = EXCLUDED.touched_at" in sql


def test_scoring_one_join_leaves_missing_totals_to_the_live_lane():
    class Conn:
        def execute(self, _sql, _args=None):
            return self

        def fetchall(self):
            return []

    assert live.score(Conn(), ["U1"]) is None


def test_a_join_is_scored_after_it_is_screened():
    import pathlib

    from bot.nemo.surface import join_watch

    src = pathlib.Path(join_watch.__file__).read_text()
    assert src.index("screening.screen(") < src.index("score_links(user[\"id\"])")


def test_a_join_whose_scoring_fails_is_left_to_the_live_lane(monkeypatch, caplog):
    import contextlib

    from bot.nemo.surface import join_watch

    @contextlib.contextmanager
    def session():
        yield object()

    def broken(_conn, _ids):
        raise RuntimeError("lock timeout")

    monkeypatch.setattr(join_watch, "session", session)
    monkeypatch.setattr(join_watch.member_links_live, "score", broken)

    assert join_watch.score_links("U1") is None
    assert "the live lane will" in caplog.text
