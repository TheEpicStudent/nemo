import datetime as dt

import pytest

from bot.core.formatting import short_date
from bot.nemo.views import action

def submission(**over):
    row = {"type_key": "shush", "target_user_id": "U1", "reason": "spamming"}
    row.update(over)
    return row


def block(blocks, block_id):
    return next((one for one in blocks if one.get("block_id") == block_id), None)


@pytest.mark.parametrize(("key", "takes", "needs"), [
    ("shush", True, False),
    ("channel_ban", True, False),
    ("temp_ban", True, True),
    ("indef_ban", False, False),
    ("warning", False, False),
])
def test_takes_expiry_needs_expiry_read_actions_table(key, takes, needs):
    assert (action.takes_expiry(key), action.needs_expiry(key)) == (takes, needs)


def test_build_blocks_shush_end_date_is_optional_with_time():
    blocks = action.build_blocks(1, submission())

    assert block(blocks, action.UNTIL)["optional"] is True
    assert block(blocks, action.UNTIL_TIME)["element"]["type"] == "timepicker"
    assert block(blocks, action.UNTIL_TIME)["optional"] is True


def test_build_blocks_temp_ban_end_date_is_required():
    assert block(action.build_blocks(1, submission(type_key="temp_ban")), action.UNTIL)["optional"] is False


def test_build_blocks_warning_omits_end_blocks():
    blocks = action.build_blocks(1, submission(type_key="warning"))

    assert block(blocks, action.UNTIL) is None
    assert block(blocks, action.UNTIL_TIME) is None


@pytest.mark.parametrize(("values", "expected"), [
    ({}, None),
    ({"expires_on": "2026-10-20"}, dt.datetime(2026, 10, 20, 23, 59, 59, tzinfo=dt.UTC)),
    ({"expires_on": "2026-10-20", "expires_time": "14:30"}, dt.datetime(2026, 10, 20, 14, 30, tzinfo=dt.UTC)),
])
def test_expiry_combines_date_and_time_in_utc(values, expected):
    assert action.expiry(values) == expected


def test_validation_errors_shush_without_end_is_valid():
    assert action.validation_errors(submission()) is None


def test_validation_errors_temp_ban_without_end_is_refused():
    assert action.validation_errors(submission(type_key="temp_ban")) == \
        {action.UNTIL: "A temporary ban needs an end date."}


def test_validation_errors_time_without_date_is_refused():
    assert action.validation_errors(submission(expires_time="14:30")) == \
        {action.UNTIL: "Pick a date for the end time."}


def test_validation_errors_date_and_time_is_valid():
    assert action.validation_errors(submission(expires_on="2026-10-16", expires_time="11:00")) is None


def test_header_text_with_expiry_shows_end_date_and_time():
    on = dt.date.today() + dt.timedelta(days=4)
    values = submission(expires_on=on.isoformat(), expires_time="14:30")

    assert action.header_text(values) == f"Shush until {short_date(on)}, 14:30 UTC"
