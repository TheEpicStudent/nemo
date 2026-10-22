import datetime as dt

import pytest

from lyla import mapping


@pytest.mark.parametrize("text, has_end, types, solution", [
    ("Warning", False, [("warning", False)], None),
    ("DM, Warning, Joined the discussion and resolved this.", False,
     [("dm", False), ("warning", False)], "Joined the discussion and resolved this."),
    ("Warning, Warning delivered by Shipwrights HQ and FD side.", False,
     [("warning", False)], "Warning delivered by Shipwrights HQ and FD side."),
    ("DM, Reversed: Warning, told them", False, [("dm", False), ("warning", True)], "told them"),
    ("Deleted messages", False, [("deleted_messages", False)], None),
])
def test_parse_action_type_with_lyla_labels_keeps_the_rest_as_solution(text, has_end, types, solution):
    assert mapping.parse_action_type(text, has_end) == (types, solution)


@pytest.mark.parametrize("text, has_end, types", [
    ("warned in thread + deleted msgs", False, ["warning", "deleted_messages"]),
    ("DMed a warning/reminder", False, ["warning", "dm"]),
    ("reached out with a DM asking them to be more considerate", False, ["dm"]),
    ("Deactivation", True, ["temp_ban"]),
    ("deactivated", False, ["indef_ban"]),
    ("deactivated the bot", False, []),
    ("DMed warning; next violation probably = ban", False, ["warning", "dm"]),
    ("Shush and ban from mc server", False, ["shush"]),
    ("perma ysws ban + warn", False, ["warning"]),
    ("Temp Ban for remainder of original shush duration", False, ["temp_ban"]),
    ("perma ban + delete", False, ["perma_ban", "deleted_messages"]),
    ("removal from channel (trying to not trigger lyla community-log)", False, ["channel_ban"]),
    ("Warned in thread + Locked thread", False, ["warning", "locked_thread"]),
    ("Ban extended to 3 months", False, ["temp_ban"]),
    ("Solved in thread", False, []),
])
def test_parse_action_type_free_text_maps_by_keyword(text, has_end, types):
    parsed, solution = mapping.parse_action_type(text, has_end)
    assert [key for key, _reversed in parsed] == types
    assert solution == text


def test_compose_action_type_round_trips_through_parse():
    types = [("shush", False), ("dm", True)]
    text = mapping.compose_action_type(types, "explained the rules")
    assert text == "Shush, Reversed: DM, explained the rules"
    assert mapping.parse_action_type(text, False) == (types, "explained the rules")


@pytest.mark.parametrize("resolved_at, resolution, status", [
    (None, None, "open"),
    (dt.datetime(2026, 1, 1, tzinfo=dt.UTC), "action_taken", "resolved"),
    (dt.datetime(2026, 1, 1, tzinfo=dt.UTC), "no_action", "resolved"),
    (dt.datetime(2026, 1, 1, tzinfo=dt.UTC), "not_conduct", "canceled"),
    (dt.datetime(2026, 1, 1, tzinfo=dt.UTC), "duplicate", "merged"),
])
def test_lyla_status_from_nemo_resolution(resolved_at, resolution, status):
    assert mapping.lyla_status(resolved_at, resolution) == status


@pytest.mark.parametrize("status, live, resolution", [
    ("resolved", True, "action_taken"),
    ("resolved", False, "no_action"),
    ("canceled", True, "not_conduct"),
    ("merged", False, "duplicate"),
    ("open", True, None),
    ("expired", True, None),
])
def test_resolution_for_lyla_status(status, live, resolution):
    assert mapping.resolution_for(status, live) == resolution


def test_thread_of_permalink_prefers_thread_ts():
    link = ("https://hackclub.slack.com/archives/C0RAID00001/p1740000000000100"
            "?thread_ts=1740000000.000050&cid=C0RAID00001")
    assert mapping.thread_of(link) == ("C0RAID00001", "1740000000.000050")


def test_thread_of_permalink_without_thread_uses_message_ts():
    link = "https://hackclub.slack.com/archives/C0OTHER0001/p1745000000000300"
    assert mapping.thread_of(link) == ("C0OTHER0001", "1745000000.000300")


def test_thread_of_text_without_permalink_is_none():
    assert mapping.thread_of("no link here") is None
    assert mapping.thread_of(None) is None


def test_ban_until_compares_at_day_precision():
    expires_at = dt.datetime(2026, 11, 30, 15, 45, tzinfo=dt.UTC)
    assert mapping.ban_until(expires_at) == "2026-11-30"
    assert mapping.same_day(expires_at, "2026-11-30")
    assert not mapping.same_day(expires_at, "2026-12-01")
    assert mapping.same_day(None, None)
    assert mapping.expiry_from("2026-11-30") == dt.datetime(2026, 11, 30, tzinfo=dt.UTC)
    assert mapping.expiry_from("not a date") is None


def test_milliseconds_round_trip():
    at = dt.datetime(2026, 10, 22, 9, 30, 5, 123000, tzinfo=dt.UTC)
    assert mapping.from_ms(mapping.to_ms(at)) == at
    assert mapping.from_ms(None) is None


def test_user_id_strips_mention_markup():
    assert mapping.user_id("<@U0123ABCD>") == "U0123ABCD"
    assert mapping.user_id("  ") is None
