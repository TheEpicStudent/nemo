import re

from lib import archive

POSTED = "1700000000.000100"


class Conn:
    def __init__(self, rowcount=0, held=None):
        self.rowcount = rowcount
        self.held = held
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
        return self.held

    def sent(self, sql):
        return [args for statement, args in self.statements if statement == sql]


def test_a_posted_message_lands_unsettled_until_history_confirms_it():
    conn = Conn()

    assert archive.from_event(conn, "C1", {"ts": POSTED, "user": "U1", "text": "hi"})
    [row] = conn.sent(archive.MESSAGE_SQL)
    assert row["channel_id"] == "C1"
    assert row["ts"] == POSTED
    assert row["settled"] is False
    assert row["author_id"] == "U1"


def test_an_edit_updates_the_held_row_in_place():
    conn = Conn(rowcount=1)
    message = {"ts": POSTED, "user": "U1", "text": "now longer than before",
               "edited": {"user": "U1", "ts": "1700000100.000000"}}

    assert archive.edited(conn, "C1", message)
    [values] = conn.sent(archive.EDIT_SQL)
    assert values["text_length"] == len("now longer than before")
    assert values["edited_by"] == "U1"
    assert values["edited_at"] == archive.stamp("1700000100.000000")
    assert conn.sent(archive.MESSAGE_SQL) == []


def test_an_edit_to_a_message_never_held_records_it():
    conn = Conn(rowcount=0, held=None)

    assert archive.edited(conn, "C1", {"ts": POSTED, "user": "U1", "text": "edited"})
    [row] = conn.sent(archive.MESSAGE_SQL)
    assert row["settled"] is False


def test_an_edit_that_changes_nothing_writes_nothing_more():
    conn = Conn(rowcount=0, held=(1,))

    assert archive.edited(conn, "C1", {"ts": POSTED, "user": "U1", "text": "same"}) is False
    assert conn.sent(archive.MESSAGE_SQL) == []


def test_an_edit_keeps_the_file_count_unless_the_files_are_sent():
    without = archive.edit_values("C1", {"ts": POSTED, "text": "x"})
    with_files = archive.edit_values("C1", {"ts": POSTED, "text": "x", "files": [{}, {}]})

    assert without["file_count"] is None
    assert with_files["file_count"] == 2
    assert without["edited_at"] is None


def test_the_edit_statement_gets_every_name_it_asks_for():
    placeholders = set(re.findall(r"%\((\w+)\)s", archive.EDIT_SQL))

    assert set(archive.edit_values("C1", {"ts": POSTED, "text": "x"})) == placeholders


def test_a_deletion_stamps_the_message_once():
    conn = Conn(rowcount=1)

    assert archive.deleted(conn, "C1", POSTED, "1700000200.000000")
    [(deleted_at, channel_id, ts)] = conn.sent(archive.DELETE_SQL)
    assert (channel_id, ts) == ("C1", POSTED)
    assert deleted_at == archive.stamp("1700000200.000000")
    assert "deleted_at IS NULL" in archive.DELETE_SQL


def test_a_deletion_without_a_usable_timestamp_is_ignored():
    conn = Conn(rowcount=1)

    assert archive.deleted(conn, "C1", None) is False
    assert archive.deleted(conn, "", POSTED) is False
    assert conn.statements == []
