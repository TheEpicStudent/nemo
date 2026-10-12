import pytest

from lib import calendar


@pytest.fixture(autouse=True)
def clear_calendar():
    calendar.clear()
    yield
    calendar.clear()
