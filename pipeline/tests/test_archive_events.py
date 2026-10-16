import re

from lib import archive

MESSAGE_TS = "1700000000.000100"


class Conn:
    def __init__(self, rowcount=0, existing_row=None):
        self.rowcount = rowcount
        self.existing_row = existing_row
        self.statements = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, args=None):
        self.statements.append((sql, args))
        return self

    def executemany(self, sql, rows):
        self.statements.extend((sql, row) for row in rows)

    def fetchone(self):
        return self.existing_row

    def args_for(self, sql):
        return [args for statement, args in self.statements if statement == sql]


def test_from_event_message_writes_unsettled_row():
    conn = Conn()

    assert archive.from_event(conn, "C1", {"ts": MESSAGE_TS, "user": "U1", "text": "hi"})
    [row] = conn.args_for(archive.MESSAGE_SQL)
    assert row["channel_id"] == "C1"
    assert row["ts"] == MESSAGE_TS
    assert row["settled"] is False
    assert row["author_id"] == "U1"


def test_edited_existing_row_updates_in_place():
    conn = Conn(rowcount=1)
    message = {"ts": MESSAGE_TS, "user": "U1", "text": "now longer than before",
               "edited": {"user": "U1", "ts": "1700000100.000000"}}

    assert archive.edited(conn, "C1", message)
    [values] = conn.args_for(archive.EDIT_SQL)
    assert values["text_length"] == len("now longer than before")
    assert values["edited_by"] == "U1"
    assert values["edited_at"] == archive.stamp("1700000100.000000")
    assert conn.args_for(archive.MESSAGE_SQL) == []


def test_edited_missing_row_inserts_unsettled_row():
    conn = Conn(rowcount=0, existing_row=None)

    assert archive.edited(conn, "C1", {"ts": MESSAGE_TS, "user": "U1", "text": "edited"})
    [row] = conn.args_for(archive.MESSAGE_SQL)
    assert row["settled"] is False


def test_edited_unchanged_row_returns_false_without_insert():
    conn = Conn(rowcount=0, existing_row=(1,))

    assert archive.edited(conn, "C1", {"ts": MESSAGE_TS, "user": "U1", "text": "same"}) is False
    assert conn.args_for(archive.MESSAGE_SQL) == []


def test_edit_values_file_count_is_none_without_files():
    without = archive.edit_values("C1", {"ts": MESSAGE_TS, "text": "x"})
    with_files = archive.edit_values("C1", {"ts": MESSAGE_TS, "text": "x", "files": [{}, {}]})

    assert without["file_count"] is None
    assert with_files["file_count"] == 2
    assert without["edited_at"] is None


def test_edit_values_keys_match_edit_sql_placeholders():
    placeholders = set(re.findall(r"%\((\w+)\)s", archive.EDIT_SQL))

    assert set(archive.edit_values("C1", {"ts": MESSAGE_TS, "text": "x"})) == placeholders


def test_deleted_stamps_deleted_at_on_undeleted_message():
    conn = Conn(rowcount=1)

    assert archive.deleted(conn, "C1", MESSAGE_TS, "1700000200.000000")
    [(deleted_at, channel_id, ts)] = conn.args_for(archive.DELETE_SQL)
    assert (channel_id, ts) == ("C1", MESSAGE_TS)
    assert deleted_at == archive.stamp("1700000200.000000")
    assert "deleted_at IS NULL" in archive.DELETE_SQL


def test_deleted_without_ts_or_channel_returns_false_and_runs_no_statement():
    conn = Conn(rowcount=1)

    assert archive.deleted(conn, "C1", None) is False
    assert archive.deleted(conn, "", MESSAGE_TS) is False
    assert conn.statements == []
