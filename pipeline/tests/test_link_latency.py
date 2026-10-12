import pathlib

from ingest import member_links as links

SQL = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0215_member_link_linked_at.sql").read_text()


def test_a_new_link_takes_its_creation_time_and_existing_links_stay_unknown():
    assert "ADD COLUMN IF NOT EXISTS linked_at timestamptz;" in SQL
    assert "ALTER COLUMN linked_at SET DEFAULT clock_timestamp()" in SQL


def test_rewriting_a_link_never_moves_when_it_first_appeared():
    assert "linked_at" not in links.UPSERT_SQL


def test_latency_runs_from_the_later_join_and_the_last_sign_in_before_the_link():
    assert "greatest(ja.joined_at, jb.joined_at)" in SQL
    assert "e.user_id IN (l.a_user_id, l.b_user_id) AND e.first_at <= l.linked_at" in SQL
    assert "WHERE l.linked_at >= now() - interval '7 days'" in SQL


def test_the_web_reads_latency_but_never_writes_it():
    assert "GRANT SELECT ON fd.link_latency TO rails_app" in SQL
