from ingest import prune
from lib import settings


def test_stamp_of_day_sources_returns_shared_analytics_stamp():
    assert prune.stamp_of("member_days") == "admin_analytics_api"
    assert prune.stamp_of("channel_days") == "admin_analytics_api"


def test_stamp_of_single_source_returns_own_key():
    assert prune.stamp_of("channel_membership") == "channel_membership"


def test_retention_column_excludes_analytics_day():
    assert "raw.analytics_day" not in prune.RETENTION_COLUMN


def test_windows_stamps_shared_tables_and_leaves_private_tables_unstamped(monkeypatch):
    monkeypatch.setattr(settings, "retention_days", lambda conn, key: 400)
    windows = prune.windows(conn=None)
    by_table = {(key, table): stamp for key, table, _, _, stamp in windows}
    assert by_table[("member_days", "raw.member_activity_snapshot")] == "admin_analytics_api"
    assert by_table[("channel_days", "raw.channel_activity_snapshot")] == "admin_analytics_api"
    assert by_table[("channel_membership", "raw.member_channel_membership")] is None
    assert not any(table == "raw.analytics_day" for _, table, _, _, _ in windows)


def test_windows_without_retention_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "retention_days", lambda conn, key: None)
    assert prune.windows(conn=None) == []


class Recorder:
    def __init__(self, deleted_rows=0):
        self.deleted_rows = deleted_rows
        self.executed = []
        self.committed = False

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.executed.append((sql, params))

    def fetchone(self):
        return (self.deleted_rows,)

    def commit(self):
        self.committed = True


def test_sweep_shared_table_adds_source_predicate():
    conn = Recorder(deleted_rows=0)
    prune.sweep(conn, "member_days", "raw.member_activity_snapshot", "window_start", 400,
                stamp="admin_analytics_api", dry_run=True)
    sql, params = conn.executed[0]
    assert "AND source = %s" in sql
    assert params == (400, "admin_analytics_api")


def test_sweep_private_table_omits_source_predicate():
    conn = Recorder(deleted_rows=0)
    prune.sweep(conn, "channel_membership", "raw.member_channel_membership", "seen_at", 60,
                stamp=None, dry_run=True)
    sql, params = conn.executed[0]
    assert "source" not in sql
    assert params == (60,)


def test_sweep_dry_run_returns_count_without_commit():
    conn = Recorder(deleted_rows=12)
    deleted = prune.sweep(conn, "member_days", "raw.member_activity_snapshot", "window_start", 400,
                          stamp="admin_analytics_api", dry_run=True)
    assert deleted == 12
    assert len(conn.executed) == 1
    assert conn.committed is False


def finished_rule(table):
    return dict(prune.FINISHED_ROW_RULES)[table]


def test_finished_row_rules_work_item_prunes_only_complete_state():
    where = finished_rule("ingest.work_item")
    assert "state = 'complete'" in where
    assert "coalesce(settled_at, updated_at) < now() - make_interval(days => %(days)s)" in where
    assert prune.FINISHED_DAYS == 90


def test_finished_row_rules_ingest_run_excludes_running_and_latest_runs():
    where = finished_rule("raw.ingest_run")
    assert "status <> 'running'" in where
    assert "id NOT IN" in where and "parent_run_id NOT IN" in where
    latest_run_ids = prune.LATEST_RUN_IDS
    assert "DISTINCT ON (source) id FROM raw.ingest_run ORDER BY source, started_at DESC" in latest_run_ids
    assert "DISTINCT ON (source_key) id FROM raw.ingest_run WHERE source_key IS NOT NULL AND status = 'ok'" in latest_run_ids


def test_finished_row_rules_step_output_requires_missing_parent_run():
    assert ("NOT EXISTS (SELECT 1 FROM raw.ingest_run r WHERE r.id = ingest_step_output.parent_run_id)"
            in finished_rule("raw.ingest_step_output"))


def test_finished_row_rules_order_ingest_run_before_step_output():
    tables = [table for table, _ in prune.FINISHED_ROW_RULES]
    assert tables.index("raw.ingest_run") < tables.index("raw.ingest_step_output")


class RowcountRecorder(Recorder):
    rowcount = 5


def test_sweep_finished_dry_run_returns_count_without_commit():
    conn = RowcountRecorder(deleted_rows=3)
    assert prune.sweep_finished(conn, "ingest.work_item", finished_rule("ingest.work_item"), dry_run=True) == 3
    sql, params = conn.executed[0]
    assert sql.startswith("SELECT count(*) FROM ingest.work_item WHERE")
    assert params == {"days": 90}
    assert conn.committed is False


def test_sweep_finished_deletes_and_commits():
    conn = RowcountRecorder()
    assert prune.sweep_finished(conn, "ingest.work_item", finished_rule("ingest.work_item")) == 5
    assert conn.executed[0][0].startswith("DELETE FROM ingest.work_item WHERE")
    assert conn.committed is True
