import pathlib

SQL = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0201_evidence_snapshot.sql").read_text()


def test_evidence_snapshot_trigger_on_guard_deactivated_event_snapshots_guard():
    assert "AFTER INSERT ON fd.member_guard_events" in SQL
    assert "WHEN (NEW.verb = 'deactivated')" in SQL
    assert "'fire_engine', g.id, g.opened_by, g.reason" in SQL


def test_evidence_snapshot_trigger_on_slack_audit_skips_deactivation_within_one_hour():
    assert "AFTER INSERT ON slack.audit_event" in SQL
    assert "WHEN (NEW.action = 'user_deactivated')" in SQL
    assert "s.deactivated_at BETWEEN NEW.at - interval '1 hour' AND NEW.at + interval '1 hour'" in SQL


def test_evidence_snapshot_trigger_on_slack_audit_skips_event_older_than_one_day():
    assert "NEW.at < now() - interval '1 day'" in SQL


def test_evidence_snapshot_includes_identity_cluster_traits_links_and_agent():
    for part in ("'email', i.email", "FROM fd.member_cluster c", "FROM fd.member_trait t",
                 "FROM fd.member_link l", "'agent', a.ua"):
        assert part in SQL


def test_evidence_snapshot_grant_is_select_insert_only():
    assert "GRANT SELECT, INSERT ON fd.evidence_snapshot TO pipeline_writer" in SQL
    assert "UPDATE" not in SQL.split("GRANT", 1)[1].split("TO pipeline_writer")[0]
