import contextlib

from bot.nemo import categories
from bot.nemo.views import action, edit, report


class Conn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, args=None):
        assert sql == categories.ALL_CATEGORIES
        return self

    def fetchall(self):
        return self.rows


def test_refresh_retired_category_is_excluded_from_active():
    rows = [("nos", "Misconduct", True), ("spam", "Spam, mass pings or invites", True), ("gone", "Gone", False)]

    assert categories.refresh(Conn(rows)) == 3
    assert list(categories.active()) == ["nos", "spam"]
    assert categories.label("gone") == "Gone"


def test_label_unknown_key_returns_humanized_key():
    assert categories.label("brand_new") == "brand new"
    assert categories.label(None) is None


def test_active_loads_table_once(monkeypatch):
    conn = Conn([("nos", "Misconduct", True)])
    session_calls = []

    @contextlib.contextmanager
    def fake_session():
        session_calls.append(1)
        yield conn

    monkeypatch.setattr(categories, "_loaded", False)
    monkeypatch.setattr(categories, "session", fake_session)

    assert categories.active() == {"nos": "Misconduct"}
    assert categories.active() == {"nos": "Misconduct"}
    assert session_calls == [1]


def test_category_choices_and_edit_categories_exclude_retired():
    assert [one["value"] for one in action.category_choices()] == ["nos", "spam"]
    assert list(edit.categories()) == ["nos", "spam"]


def test_report_category_label_retired_category_returns_label():
    assert report.category_label("old_kind") == "Retired kind"
