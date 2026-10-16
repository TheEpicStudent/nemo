import pathlib

from ingest import member_links as links

SQL = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0215_member_link_linked_at.sql").read_text()


def test_member_link_linked_at_column_is_nullable_with_clock_timestamp_default():
    assert "ADD COLUMN IF NOT EXISTS linked_at timestamptz;" in SQL
    assert "ALTER COLUMN linked_at SET DEFAULT clock_timestamp()" in SQL


def test_upsert_sql_does_not_write_linked_at():
    assert "linked_at" not in links.UPSERT_SQL


def test_link_latency_view_measures_from_later_join_and_last_sign_in_before_link():
    assert "greatest(ja.joined_at, jb.joined_at)" in SQL
    assert "e.user_id IN (l.a_user_id, l.b_user_id) AND e.first_at <= l.linked_at" in SQL
    assert "WHERE l.linked_at >= now() - interval '7 days'" in SQL


def test_link_latency_grants_select_only_to_rails_app():
    assert "GRANT SELECT ON fd.link_latency TO rails_app" in SQL
