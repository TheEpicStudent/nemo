import datetime as dt

from bot.core.formatting import short_date
from bot.nemo import command, record
from bot.nemo.enforcement import notify, sweep
from bot.nemo.views import action, resolve

TODAY = dt.date(2026, 10, 15)
NEXT_YEAR = dt.date.today().year + 1
NEXT_YEAR_DATE = dt.date(NEXT_YEAR, 10, 15)
NEXT_YEAR_TIMESTAMP = dt.datetime(NEXT_YEAR, 10, 15, 23, 59, 59, tzinfo=dt.UTC)
NEXT_YEAR_LABEL = f"15 Oct {NEXT_YEAR}"


def test_short_date_omits_current_year():
    assert short_date(dt.date(2026, 11, 3), today=TODAY) == "3 Nov"


def test_short_date_includes_other_year():
    assert short_date(dt.date(2027, 10, 15), today=TODAY) == "15 Oct 2027"
    assert short_date(dt.date(2025, 12, 31), today=TODAY) == "31 Dec 2025"


def test_short_date_accepts_timestamps():
    timestamp = dt.datetime(2027, 1, 2, 23, 59, 59, tzinfo=dt.UTC)
    assert short_date(timestamp, today=TODAY) == "2 Jan 2027"


def test_shush_and_channel_ban_replies_show_next_year():
    assert NEXT_YEAR_LABEL in command.shushed("U1", NEXT_YEAR_DATE)
    assert NEXT_YEAR_LABEL in command.banned("U1", "C1", NEXT_YEAR_DATE)


def test_member_dm_shows_next_year():
    assert notify.ending({"expires_at": NEXT_YEAR_TIMESTAMP}) == f"until {NEXT_YEAR_LABEL}"


def test_lookup_line_shows_next_year():
    guard = {"kind": "shush", "expires_at": NEXT_YEAR_TIMESTAMP}
    assert NEXT_YEAR_LABEL in record.in_force_line(guard)


def test_ending_soon_line_shows_next_year():
    guard = {"subject_id": "U1", "kind": "shush", "expires_at": NEXT_YEAR_TIMESTAMP}
    assert NEXT_YEAR_LABEL in sweep.line_about(guard)


def test_action_summary_and_resolve_dialog_show_next_year():
    assert action.format_date(NEXT_YEAR_TIMESTAMP) == NEXT_YEAR_LABEL
    assert resolve.until(NEXT_YEAR_TIMESTAMP) == NEXT_YEAR_LABEL
