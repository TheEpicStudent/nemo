import datetime as dt

from bot.core.formatting import short_date, short_end, short_end_token
from bot.nemo import command, record
from bot.nemo.enforcement import notify, sweep
from bot.nemo.views import action

TODAY = dt.date(2026, 10, 15)
NEXT_YEAR = dt.date.today().year + 1
NEXT_YEAR_TIMESTAMP = dt.datetime(NEXT_YEAR, 10, 15, 23, 59, 59, tzinfo=dt.UTC)
NEXT_YEAR_LABEL = f"15 Oct {NEXT_YEAR}"


def test_short_date_current_year_omits_year():
    assert short_date(dt.date(2026, 11, 3), today=TODAY) == "3 Nov"


def test_short_date_other_year_includes_year():
    assert short_date(dt.date(2027, 10, 15), today=TODAY) == "15 Oct 2027"
    assert short_date(dt.date(2025, 12, 31), today=TODAY) == "31 Dec 2025"


def test_short_date_datetime_input_returns_date_label():
    timestamp = dt.datetime(2027, 1, 2, 23, 59, 59, tzinfo=dt.UTC)
    assert short_date(timestamp, today=TODAY) == "2 Jan 2027"


def test_shush_and_ban_confirmation_next_year_includes_year():
    assert NEXT_YEAR_LABEL in command.shush_confirmation("U1", NEXT_YEAR_TIMESTAMP, "spamming")
    assert NEXT_YEAR_LABEL in command.ban_confirmation("U1", "C1", NEXT_YEAR_TIMESTAMP, "spamming")


def test_short_end_end_of_day_returns_date_only():
    assert short_end(dt.datetime(2026, 11, 3, 23, 59, 59, tzinfo=dt.UTC), today=TODAY) == "3 Nov"


def test_short_end_mid_day_returns_date_and_utc_time():
    assert short_end(dt.datetime(2026, 11, 3, 14, 5, tzinfo=dt.UTC), today=TODAY) == "3 Nov, 14:05 UTC"


def test_short_end_non_utc_zone_converts_to_utc():
    cairo = dt.timezone(dt.timedelta(hours=3))
    assert short_end(dt.datetime(2026, 11, 3, 17, 5, tzinfo=cairo), today=TODAY) == "3 Nov, 14:05 UTC"


def test_short_end_date_input_returns_date_only():
    assert short_end(dt.date(2026, 11, 3), today=TODAY) == "3 Nov"


def test_notify_ending_next_year_includes_year():
    assert notify.ending({"expires_at": NEXT_YEAR_TIMESTAMP}) == f"until {NEXT_YEAR_LABEL}"


def test_in_force_line_next_year_includes_year():
    guard = {"kind": "shush", "expires_at": NEXT_YEAR_TIMESTAMP}
    assert NEXT_YEAR_LABEL in record.in_force_line(guard)


def test_ending_line_next_year_includes_year():
    guard = {"subject_id": "U1", "kind": "shush", "expires_at": NEXT_YEAR_TIMESTAMP}
    assert NEXT_YEAR_LABEL in sweep.ending_line(guard)


def test_format_date_next_year_includes_year():
    assert action.format_date(NEXT_YEAR_TIMESTAMP) == NEXT_YEAR_LABEL


def test_short_end_token_mid_day_returns_viewer_local_date_token_with_utc_fallback():
    at = dt.datetime(2026, 11, 3, 14, 5, tzinfo=dt.UTC)

    assert short_end_token(at, today=TODAY) == (
        f"<!date^{int(at.timestamp())}^{{date_short_pretty}} at {{time}}|3 Nov 2026, 14:05 UTC>")


def test_short_end_token_non_utc_zone_uses_the_same_instant():
    cairo = dt.timezone(dt.timedelta(hours=3))

    assert short_end_token(dt.datetime(2026, 11, 3, 17, 5, tzinfo=cairo), today=TODAY) == short_end_token(
        dt.datetime(2026, 11, 3, 14, 5, tzinfo=dt.UTC), today=TODAY)


def test_short_end_token_naive_datetime_is_read_as_utc():
    assert short_end_token(dt.datetime(2026, 11, 3, 14, 5), today=TODAY) == short_end_token(
        dt.datetime(2026, 11, 3, 14, 5, tzinfo=dt.UTC), today=TODAY)


def test_short_end_token_end_of_day_and_dates_stay_plain_utc_dates():
    assert short_end_token(dt.datetime(2026, 11, 3, 23, 59, 59, tzinfo=dt.UTC), today=TODAY) == "3 Nov"
    assert short_end_token(dt.date(2026, 11, 3), today=TODAY) == "3 Nov"
