import contextlib

from bot.nemo import categories
from bot.nemo.views import action, edit, report


class Conn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, args=None):
        assert sql == categories.ALL
        return self

    def fetchall(self):
        return self.rows


def test_refresh_keeps_order_and_leaves_retired_out_of_active():
    rows = [("nos", "Misconduct", True), ("spam", "Spam, mass pings or invites", True), ("gone", "Gone", False)]

    assert categories.refresh(Conn(rows)) == 3
    assert list(categories.active()) == ["nos", "spam"]
    assert categories.label("gone") == "Gone"


def test_label_of_an_unknown_key_reads_the_key():
    assert categories.label("brand_new") == "brand new"
    assert categories.label(None) is None


def test_ensure_loaded_reads_the_table_once(monkeypatch):
    conn = Conn([("nos", "Misconduct", True)])
    opened = []

    @contextlib.contextmanager
    def session_of():
        opened.append(1)
        yield conn

    monkeypatch.setattr(categories, "_loaded", False)
    monkeypatch.setattr(categories, "session", session_of)

    assert categories.active() == {"nos": "Misconduct"}
    assert categories.active() == {"nos": "Misconduct"}
    assert opened == [1]


def test_pickers_offer_only_active_categories():
    assert [one["value"] for one in action.category_choices()] == ["nos", "spam"]
    assert list(edit.categories()) == ["nos", "spam"]


def test_card_labels_cover_retired_categories():
    assert report.category_label("old_kind") == "Retired kind"
