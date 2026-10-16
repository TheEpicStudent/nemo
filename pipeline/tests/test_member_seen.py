from datetime import UTC, datetime, timedelta

from ingest import access_logs_pull
from lib import archive, member_seen

EARLY = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
LATE = EARLY + timedelta(hours=5)


class Conn:
    def __init__(self):
        self.executed = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def executemany(self, sql, rows):
        self.executed.append((sql, rows))

    def fetchall(self):
        return []

    def commit(self):
        pass

    def member_seen_args(self):
        return [args for sql, args in self.executed if "fd.member_seen" in sql]


class Counts:
    rows_in = 0
    rows_rejected = 0


def test_latest_pairs_return_one_row_per_member_at_newest_time():
    pairs = [("U2", EARLY), ("U1", LATE), ("U2", LATE), ("U1", EARLY)]

    assert member_seen.latest(pairs) == [("U1", LATE), ("U2", LATE)]


def test_latest_pair_missing_member_or_time_is_dropped():
    assert member_seen.latest([("", LATE), (None, LATE), ("U1", None)]) == []


def test_posted_and_logged_in_without_valid_pairs_execute_nothing():
    conn = Conn()
    member_seen.posted(conn, [])
    member_seen.logged_in(conn, [("U1", None)])

    assert conn.executed == []


def test_posted_batch_executes_one_statement_with_latest_time_per_member():
    conn = Conn()
    member_seen.posted(conn, [("U2", EARLY), ("U1", LATE), ("U2", LATE)])

    assert conn.executed == [(member_seen.POSTED_SQL, (["U1", "U2"], [LATE, LATE]))]


def test_posted_and_logged_in_sql_only_advance_times():
    for sql, column in ((member_seen.POSTED_SQL, "last_post_at"),
                        (member_seen.LOGGED_IN_SQL, "last_login_at")):
        assert f"existing.{column} >= incoming.at" in sql, "a member already this fresh is not touched"
        assert f"target.{column} < EXCLUDED.{column}" in sql


def test_member_posts_skips_subtype_bot_and_userless_messages():
    def row(**message):
        return archive.message_row("C1", message["ts"], 1, message, {})

    post = row(ts="1700000000.000100", user="U1", text="hi")
    joined = row(ts="1700000000.000200", user="U2", subtype="channel_join")
    bot = row(ts="1700000000.000300", bot_id="B1")
    userless = row(ts="1700000000.000400")

    assert archive.member_posts([post, joined, bot, userless]) == [("U1", post[3])]


def test_from_api_many_updates_member_seen_once_per_poster_with_latest_time():
    conn = Conn()
    archive.from_api_many(conn, "C1", [
        {"ts": "1700000000.000100", "user": "U1", "text": "hi"},
        {"ts": "1700000100.000100", "user": "U1", "text": "again"},
        {"ts": "1700000200.000100", "user": "U2", "subtype": "channel_join"},
    ], "conversations.history", "history")

    assert conn.member_seen_args() == [(["U1"], [archive.stamp("1700000100.000100")])]


def test_insert_rows_access_log_updates_member_seen_with_latest_login():
    conn = Conn()
    access_logs_pull.insert_rows(conn, [
        {"user_id": "U1", "date_first": 1790000000, "date_last": 1790003600},
        {"user_id": "U1", "date_first": 1790000000, "date_last": 1790001800, "ip": "10.0.0.1"},
    ], Counts())

    assert conn.member_seen_args() == [(["U1"], [datetime.fromtimestamp(1790003600, tz=UTC)])]
