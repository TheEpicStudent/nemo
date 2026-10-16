import pytest

from bot.nemo import categories
from lib import calendar

KNOWN_CATEGORIES = {"nos": "Misconduct not otherwise specified", "spam": "Spam, mass pings or invites",
                    "old_kind": "Retired kind"}


@pytest.fixture(autouse=True)
def clear_calendar():
    calendar.clear()
    yield
    calendar.clear()


@pytest.fixture(autouse=True)
def known_categories(monkeypatch):
    monkeypatch.setattr(categories, "_labels", dict(KNOWN_CATEGORIES))
    monkeypatch.setattr(categories, "_active", ["nos", "spam"])
    monkeypatch.setattr(categories, "_loaded", True)
