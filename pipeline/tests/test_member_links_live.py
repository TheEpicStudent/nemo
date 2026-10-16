from ingest import member_links as links
from ingest import member_links_live as live


def test_cap_exceeds_largest_signal_ceiling():
    ceilings = [definition.get("crowd_ceiling", 0) for definition in links.signals().values()]
    assert live.CAP > max(ceilings)


def test_rescored_and_scope_user_sql_limit_to_touched_members():
    assert "SELECT user_id FROM touched" in live.RESCORED
    assert "WHERE v.user_count <= %(cap)s" in live.SCOPE_USER
    assert "SELECT value FROM scope_value WHERE kind = 'inviter'" in live.SCOPE_USER


def test_scope_sql_loads_whole_prefixes_and_exit_addresses():
    assert "WHERE n.class IS NULL OR n.class NOT IN ('rotating', 'vpn', 'hosting', 'tor')" in live.SCOPE_PREFIX
    assert "n.class IN ('rotating', 'vpn', 'hosting', 'tor')" in live.SCOPE_EXIT
    assert "WHERE e.user_id IN (SELECT user_id FROM rescored) AND e.ip IS NOT NULL" in live.SCOPE_EXIT
    assert "e.ip_prefix IN (SELECT ip_prefix FROM scope_prefix)" in live.SCOPE_LOGIN
    assert "WHERE e.ip IN (SELECT ip FROM scope_exit)" in live.SCOPE_LOGIN
    assert "e.ip_prefix NOT IN (SELECT ip_prefix FROM scope_prefix)" in live.SCOPE_LOGIN
    assert "e.ip NOT IN (SELECT ip FROM scope_exit)" in live.SCOPE_LOGIN


def test_scope_orders_rescored_and_exit_before_login():
    order = list(live.SCOPE)

    assert order.index(live.RESCORED) < order.index(live.SCOPE_EXIT) < order.index(live.SCOPE_LOGIN)
    assert order.index(live.SCOPE_PREFIX) < order.index(live.SCOPE_LOGIN)


def test_live_sources_use_shared_ip_table_and_over_cap():
    assert live.LIVE["shared_ip"] == "fd.shared_ip"
    assert live.LIVE["over_cap"] == "over_cap"
    assert "fd.shared_ip" in live.LIVE["sighting"]


def test_live_sighting_sql_reads_login_events_of_live_pair_members():
    assert "FROM fd.login_event WHERE user_id IN (SELECT a_user_id FROM link_pass" in live.LIVE["sighting"]


def test_only_rescored_and_sweep_sql_limit_to_rescored_members():
    assert "a_user_id NOT IN (SELECT user_id FROM rescored)" in live.ONLY_RESCORED
    assert "l.a_user_id IN (SELECT user_id FROM rescored) OR l.b_user_id IN" in live.SWEEP


def test_done_sql_deletes_touch_only_when_touched_at_unchanged():
    assert "t.touched_at = done.touched_at" in live.DONE_SQL


def test_run_measures_missing_totals_without_full_rebuild(monkeypatch, capsys):
    executed = []

    class Conn:
        def execute(self, sql, _args=None):
            executed.append(sql)
            return self

        def fetchall(self):
            return []

        def fetchone(self):
            return (40,)

        def commit(self):
            executed.append("COMMIT")

    monkeypatch.setattr(live.links, "load_mailboxes", lambda _conn, _config, _sources: executed.append("MAILBOXES"))

    assert live.run(Conn()) == 0
    assert "without a full rebuild" in capsys.readouterr().out
    assert any("CREATE TEMP TABLE sighting" in sql and "fd.shared_ip" in sql for sql in executed)
    assert "MAILBOXES" in executed
    assert executed.index(live.links.SAVE_WHOLES_SQL) < executed.index("COMMIT") < executed.index(live.TOUCHED_SQL)


class Queue:
    def __init__(self, recent, queued):
        self.recent = recent
        self.queued = queued
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        sql, _ = self.executed[-1]
        return self.recent if sql == live.RECENT_JOINS_SQL else self.queued


def test_next_batch_returns_recent_joins_first():
    conn = Queue(recent=[("U1", "t1")], queued=[("U9", "t0")])

    assert live.next_batch(conn, 40) == [("U1", "t1")]
    assert conn.executed == [(live.RECENT_JOINS_SQL, (live.RECENT_JOIN_DAYS, 40))]


def test_next_batch_without_recent_joins_returns_touched_queue():
    conn = Queue(recent=[], queued=[("U9", "t0")])

    assert live.next_batch(conn, 40) == [("U9", "t0")]
    assert conn.executed[-1] == (live.TOUCHED_SQL, (40,))


def test_recent_joins_sql_filters_by_join_age_and_orders_by_touched_at():
    assert live.RECENT_JOIN_DAYS == 7
    assert "j.joined_at > now() - make_interval(days => %s)" in live.RECENT_JOINS_SQL
    assert "ORDER BY t.touched_at" in live.RECENT_JOINS_SQL


def test_measure_sources_map_to_whole_tables_and_shared_ip():
    assert live.MEASURE_SOURCES["login"] == "fd.login_event"
    assert live.MEASURE_SOURCES["identity"] == "fd.member_identity"
    assert live.MEASURE_SOURCES["shared_ip"] == "fd.shared_ip"


def test_measure_with_one_missing_total_runs_one_query():
    class Conn:
        def __init__(self):
            self.executed = []

        def execute(self, sql, _args=None):
            self.executed.append(sql)
            return self

        def fetchone(self):
            return (40,)

    conn = Conn()
    counts = links.measure(conn, links.catalogue(), live.MEASURE_SOURCES, ["device_agent"])
    assert counts == {"device_agent": 40}
    assert len(conn.executed) == 1


def test_live_links_migration_adds_triggers_that_queue_member():
    import pathlib

    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0199_live_links.sql").read_text()
    assert "AFTER INSERT OR UPDATE OR DELETE ON fd.member_trait" in sql
    assert "AFTER INSERT OR UPDATE OF joined_at ON fd.member_joins" in sql
    assert "WHEN (NEW.action IN ('user_deactivated', 'user_reactivated'))" in sql
    assert "ON CONFLICT (user_id) DO UPDATE SET touched_at = EXCLUDED.touched_at" in sql


def test_score_with_missing_wholes_returns_none():
    class Conn:
        def execute(self, _sql, _args=None):
            return self

        def fetchall(self):
            return []

    assert live.score(Conn(), ["U1"]) is None


def test_join_watch_scores_links_after_screening():
    import pathlib

    from bot.nemo.surface import join_watch

    src = pathlib.Path(join_watch.__file__).read_text()
    assert src.index("screening.screen(") < src.index("score_links(user[\"id\"])")


def test_score_links_with_failing_score_returns_none_and_logs(monkeypatch, caplog):
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


def test_batch_sizer_first_batch_then_scales_to_budget():
    sizer = live.BatchSizer()
    assert sizer.batch(60) == live.FIRST_BATCH

    sizer.record(50, 50, 30.0)
    assert sizer.batch(60) == 75

    sizer.record(75, 75, 450.0)
    assert sizer.batch(60) == live.SMALLEST_BATCH


def test_batch_sizer_quick_pass_doubles_batch_up_to_largest():
    sizer = live.BatchSizer()
    sizer.record(50, 2, 0.2)

    assert sizer.batch(60) == 100
    sizer.record(200, 200, 1.0)
    assert sizer.batch(60) == live.LARGEST_BATCH


def test_run_records_steps_under_run_id_and_updates_batch_sizer(monkeypatch):
    import contextlib

    recorded = {}

    class Conn:
        def execute(self, sql, params=None):
            return self

        def fetchall(self):
            return [("U1", "t1"), ("U2", "t2")]

        def commit(self):
            pass

    @contextlib.contextmanager
    def fake_ingest_run(*_args, **_kwargs):
        yield type("Counts", (), {"rows_in": 0, "run_id": 77})()

    def fake_rescore(_conn, _catalogue, _wholes, touched, steps):
        for name in ("scope", "prepare", "gather", "settle"):
            with live.timed_step(steps, name):
                pass
        return len(touched), 3, 2, 1, {}

    monkeypatch.setattr(live, "ensure_wholes", lambda _conn, _catalogue, wholes: wholes)
    monkeypatch.setattr(live.links, "load_wholes", lambda _conn: {})
    monkeypatch.setattr(live, "ingest_run", fake_ingest_run)
    monkeypatch.setattr(live, "rescore", fake_rescore)
    monkeypatch.setattr(live, "record_steps", lambda _conn, run_id, steps: recorded.update(run_id=run_id, steps=steps))
    sizer = live.BatchSizer()

    assert live.run(Conn(), sizer) == 2
    assert recorded["run_id"] == 77
    assert [source for source, _started, _finished in recorded["steps"]] == [
        "member_links_live:scope", "member_links_live:prepare", "member_links_live:gather", "member_links_live:settle"]
    assert sizer.seconds_per_member is not None and sizer.last_batch == live.FIRST_BATCH


def test_steps_sql_inserts_child_runs_and_record_steps_skips_empty_input():
    from lib import db

    sql = db.STEPS_SQL
    assert "parent.id, step.step_index, %(total)s" in sql
    assert "SELECT step.source, step.source, parent.logical_date, parent.worker, parent.worker_boot" in sql
    assert "WITH ORDINALITY AS step (source, started_at, finished_at, step_index)" in sql

    class Conn:
        def execute(self, *_args):
            raise AssertionError("nothing to record")

    db.record_steps(Conn(), None, [("x", 1, 2)])
    db.record_steps(Conn(), 5, [])
