import json
from datetime import date, datetime, timedelta, timezone

from bot.nemo import new_members
from ingest import (
    analytics_pull,
    channel_history_pull,
    channel_range_pull,
    member_channels,
    member_history,
    member_range_pull,
    users_list_pull,
)
from lib import message as shaping

PULL_DATE = date(2026, 7, 20)
WINDOW_START = date(2026, 6, 30)
WINDOW_END = date(2026, 7, 29)


def epoch(value):
    return datetime.fromtimestamp(value, tz=timezone.utc)


def test_member_activity_row_maps_day_and_message_counts():
    rec = {
        "user_id": "U1",
        "days_active": 4,
        "days_active_desktop": 3,
        "days_active_ios": 0,
        "messages_posted": 12,
        "messages_posted_in_channel": 9,
        "reactions_added": 5,
        "date_last_active": 1700000000,
    }
    row = analytics_pull.member_activity_row(rec, PULL_DATE)
    assert len(row) == 22
    assert row[0:4] == ("U1", PULL_DATE, PULL_DATE, analytics_pull.ANALYTICS_SOURCE)
    assert row[4] == 4
    assert row[5] == 3
    assert row[7] == 0
    assert row[11] == 12
    assert row[12] == 9
    assert row[13] == 5
    assert row[18] == epoch(1700000000)


def test_member_activity_row_with_window_sets_dates_and_source():
    row = analytics_pull.member_activity_row(
        {"user_id": "U1", "messages_posted": 12}, WINDOW_START, WINDOW_END, member_range_pull.SOURCE
    )
    assert row[0:4] == ("U1", WINDOW_START, WINDOW_END, member_range_pull.SOURCE)
    assert row[11] == 12
    assert member_range_pull.SOURCE != analytics_pull.ANALYTICS_SOURCE


def test_member_activity_row_omitted_fields_are_none():
    row = analytics_pull.member_activity_row({"user_id": "U1"}, PULL_DATE)
    assert row[9] is None
    assert row[10] is None


def test_idle_zero_counts_returns_true():
    row = analytics_pull.member_activity_row(
        {"user_id": "U1", "days_active": 0, "messages_posted": 0, "date_last_active": 1700000000},
        PULL_DATE,
    )
    assert analytics_pull.idle(row)


def test_idle_any_nonzero_count_returns_false():
    count_fields = ("days_active", "days_active_desktop", "days_active_android", "days_active_ios",
                    "days_active_slack_connect", "messages_posted", "messages_posted_in_channel",
                    "reactions_added", "files_added_count", "slack_huddles_count", "search_count",
                    "channels_joined_count")
    for field in count_fields:
        row = analytics_pull.member_activity_row({"user_id": "U1", field: 1}, PULL_DATE)
        assert not analytics_pull.idle(row), f"{field} alone must keep the day"


def test_member_dim_row_maps_invited_flags_and_pull_date():
    row = analytics_pull.member_dim_row(
        {"user_id": "U1", "is_invited_member": True, "is_invited_guest": False}, PULL_DATE
    )
    assert row[2] is True and row[3] is False
    assert row[4] == PULL_DATE


def test_member_dim_row_converts_date_claimed_and_defaults_member_flag_false():
    row = analytics_pull.member_dim_row(
        {"user_id": "U1", "date_claimed": 1600000000, "is_invited_guest": True}, PULL_DATE
    )
    assert row == ("U1", epoch(1600000000), False, True, PULL_DATE)


def test_channel_activity_row_maps_message_and_member_counts():
    rec = {
        "channel_id": "C1",
        "messages_posted_count": 10,
        "messages_posted_by_members_count": 7,
        "members_who_posted_count": 4,
        "members_who_viewed_count": 30,
        "reactions_added_count": 2,
        "total_members_count": 44295,
        "full_members_count": 42717,
        "guest_members_count": 1578,
    }
    row = analytics_pull.channel_activity_row(rec, PULL_DATE)
    assert len(row) == 15
    assert row[0] == "C1"
    assert row[4] == 10
    assert row[5] == 7
    assert row[6] == 4
    assert row[8] == 30
    assert row[9] == 2


def test_channel_activity_row_maps_membership_counts():
    rec = {"channel_id": "C1", "total_members_count": 44295,
           "full_members_count": 42717, "guest_members_count": 1578}
    row = analytics_pull.channel_activity_row(rec, PULL_DATE)
    assert row[12:15] == (44295, 42717, 1578)


def test_channel_dim_row_converts_date_created_to_datetime():
    row = analytics_pull.channel_dim_row(
        {"channel_id": "C1", "visibility": "public", "date_created": 1700000000}
    )
    assert len(row) == 4
    assert row[0] == "C1"
    assert row[2] == epoch(1700000000)


def test_channel_dim_row_excludes_membership_count():
    row = analytics_pull.channel_dim_row(
        {"channel_id": "C1", "visibility": "public", "total_members_count": 281}
    )
    assert 281 not in row


def test_users_list_member_dim_row_maps_deleted_flag():
    row = users_list_pull.member_dim_row(
        {"id": "U1", "deleted": True, "is_bot": False, "is_ultra_restricted": True}
    )
    assert len(row) == 9
    assert row[0:3] == ("U1", True, False)
    assert row[7] is True


def test_users_list_member_dim_row_invite_pending_follows_is_invited_user_presence():
    without_flag = users_list_pull.member_dim_row({"id": "U1"})
    with_flag = users_list_pull.member_dim_row({"id": "U2", "is_invited_user": True})
    assert without_flag[8] is False
    assert with_flag[8] is True


def test_users_list_member_row_maps_admin_and_owner_flags():
    with_flags = users_list_pull.member_row({"id": "U1", "is_admin": True, "is_owner": True})
    without_flags = users_list_pull.member_row({"id": "U2"})
    assert with_flags[7:9] == (True, True)
    assert without_flags[7:9] == (False, False)


def test_users_list_member_row_maps_enterprise_admin_and_owner_flags():
    enterprise_row = users_list_pull.member_row({"id": "U1", "is_admin": False,
                                                 "enterprise_user": {"is_admin": True, "is_owner": True}})
    without_flags = users_list_pull.member_row({"id": "U2"})
    assert enterprise_row[7:11] == (False, False, True, True)
    assert without_flags[9:11] == (False, False)


def test_users_list_member_sql_placeholder_count_equals_row_length():
    row = users_list_pull.member_row({"id": "U1"})
    assert users_list_pull.MEMBER_SQL.count("%s") == len(row)


def test_new_members_member_row_maps_admin_and_owner_flags():
    with_flags = new_members.member_row({"id": "U1", "is_admin": True, "is_owner": False})
    without_flags = new_members.member_row({"id": "U2"})
    assert with_flags[9:11] == (True, False)
    assert without_flags[9:11] == (False, False)


def test_new_members_member_row_maps_enterprise_admin_and_owner_flags():
    enterprise_row = new_members.member_row({"id": "U1", "enterprise_user": {"is_admin": True, "is_owner": False}})
    without_flags = new_members.member_row({"id": "U2"})
    assert enterprise_row[9:13] == (False, False, True, False)
    assert without_flags[11:13] == (False, False)


def test_new_members_member_sql_placeholder_count_equals_row_length():
    row = new_members.member_row({"id": "U1"})
    assert new_members.MEMBER.count("%s") == len(row)


CALENDAR_START = date(2026, 7, 1)
CALENDAR_END = date(2026, 7, 10)


def test_pending_days_returns_newest_missing_days_descending():
    loaded = {date(2026, 7, 3), date(2026, 7, 4)}
    assert analytics_pull.pending_days(loaded, CALENDAR_START, CALENDAR_END, 4) == [
        date(2026, 7, 10),
        date(2026, 7, 9),
        date(2026, 7, 8),
        date(2026, 7, 7),
    ]


def test_pending_days_skips_loaded_days():
    loaded = {date(2026, 7, 9), date(2026, 7, 10)}
    assert analytics_pull.pending_days(loaded, CALENDAR_START, CALENDAR_END, 3) == [
        date(2026, 7, 8),
        date(2026, 7, 7),
        date(2026, 7, 6),
    ]


def test_pending_days_limit_one_returns_newest_day():
    assert analytics_pull.pending_days(set(), CALENDAR_START, CALENDAR_END, 1) == [date(2026, 7, 10)]


def test_pending_days_all_days_loaded_returns_empty():
    all_days = set()
    day = CALENDAR_START
    while day <= CALENDAR_END:
        all_days.add(day)
        day += timedelta(days=1)
    assert analytics_pull.pending_days(all_days, CALENDAR_START, CALENDAR_END, 5) == []


def test_pending_days_result_length_capped_at_limit():
    assert len(analytics_pull.pending_days(set(), CALENDAR_START, CALENDAR_END, 3)) == 3


def test_pending_days_loaded_days_outside_range_are_ignored():
    loaded = {date(2020, 1, 1), date(2026, 7, 10)}
    assert analytics_pull.pending_days(loaded, CALENDAR_START, CALENDAR_END, 2) == [
        date(2026, 7, 9),
        date(2026, 7, 8),
    ]


AVAIL_START = date(2026, 5, 15)
AVAIL_END = date(2026, 8, 2)


def test_verified_date_row_maps_created_and_claimed_dates():
    row = member_range_pull.verified_date_row(
        {"user_id": "U1", "date_created": 1600000000, "date_claimed": 1600000500}
    )
    assert row == ("U1", epoch(1600000000), epoch(1600000500))


def test_verified_date_row_without_date_claimed_returns_none_claimed():
    row = member_range_pull.verified_date_row({"user_id": "U1", "date_created": 1600000000})
    assert row == ("U1", epoch(1600000000), None)


def test_range_row_maps_message_chat_writer_and_reader_counts():
    rec = {
        "channel_id": "C1",
        "messages_count": 151576,
        "chats_count": 9,
        "writers_count": 2,
        "readers_count": 3,
        "reactions_count": 1,
        "users_who_reacted_count": 1,
        "huddles_count": 0,
        "total_members_count": 44295,
        "full_members_count": 42717,
        "guest_members_count": 1578,
    }
    row = channel_range_pull.range_row(rec, WINDOW_START, WINDOW_END)
    assert len(row) == 16
    assert row[0:4] == ("C1", WINDOW_START, WINDOW_END, channel_range_pull.SOURCE)
    assert row[4] == 151576
    assert row[5] == 9
    assert row[6] == 2
    assert row[7] == 3
    assert row[9] == 1
    assert row[10] == 0


def test_range_row_maps_membership_counts():
    rec = {"channel_id": "C1", "total_members_count": 44295,
           "full_members_count": 42717, "guest_members_count": 1578}
    row = channel_range_pull.range_row(rec, WINDOW_START, WINDOW_END)
    assert row[11:14] == (44295, 42717, 1578)


def test_stamp_epoch_seconds_returns_utc_datetime():
    assert channel_range_pull.stamp(1768352025) == datetime(
        2026, 1, 14, 0, 53, 45, tzinfo=timezone.utc)


def test_stamp_empty_values_return_none():
    for empty in (None, "", 0):
        assert channel_range_pull.stamp(empty) is None


def test_stamp_negative_one_returns_none():
    assert channel_range_pull.stamp(-1) is None, \
        "slack sends -1 for a channel nothing was ever posted in"


def test_stamp_unparseable_value_returns_none():
    for bad in ("not a stamp", 10 ** 20, [1]):
        assert channel_range_pull.stamp(bad) is None


def test_range_row_maps_created_and_last_message_dates():
    rec = {"channel_id": "C1", "date_create": 1768352025,
           "last_message_posted": 1787964291}
    row = channel_range_pull.range_row(rec, WINDOW_START, WINDOW_END)
    assert row[14] == channel_range_pull.stamp(1768352025)
    assert row[15] == channel_range_pull.stamp(1787964291)
    assert row[14] < row[15]


class FakeClient:
    def __init__(self, start="2025-07-01", end="2026-08-01"):
        self.range = {"ok": True, "start_date": start, "end_date": end}
        self.calls = []

    def call(self, method, params):
        self.calls.append((method, params))
        return self.range


def test_resolve_window_requests_channel_calendar():
    client = FakeClient()
    start, end = channel_range_pull.resolve_window(client)
    assert client.calls == [(channel_range_pull.RANGE_METHOD, {"type": "channel"})]
    assert end == date(2026, 8, 1)
    assert start == date(2026, 7, 3)


def test_resolve_window_clamps_start_to_calendar_floor():
    client = FakeClient(start="2026-07-20", end="2026-08-01")
    start, end = channel_range_pull.resolve_window(client)
    assert (start, end) == (date(2026, 7, 20), date(2026, 8, 1))


def test_resolve_window_explicit_end_sets_window_end():
    client = FakeClient()
    start, end = channel_range_pull.resolve_window(client, days=7, end=date(2026, 7, 10))
    assert (start, end) == (date(2026, 7, 4), date(2026, 7, 10))


def test_channel_calendar_nested_range_returns_dates():
    class Nested(FakeClient):
        def call(self, method, params):
            return {"ok": True, "available_date_range": self.range}

    assert channel_range_pull.channel_calendar(Nested()) == (date(2025, 7, 1), date(2026, 8, 1))


def test_history_row_maps_total_and_first_match():
    messages = {
        "total": 6009,
        "matches": [{"ts": "1606939916.452200", "channel": {"id": "C75M7C0SY", "name": "welcome"}}],
    }
    row = member_history.history_row("U1", messages)
    assert row == ("U1", 6009, epoch(1606939916.4522), "C75M7C0SY")


def test_history_row_zero_total_returns_none_first_post():
    assert member_history.history_row("U1", {"total": 0, "matches": []}) == ("U1", 0, None, None)


def test_history_row_total_without_matches_returns_none_first_post():
    assert member_history.history_row("U1", {"total": 3, "matches": []}) == ("U1", 3, None, None)


def test_history_row_skips_dm_and_private_matches():
    messages = {
        "total": 4,
        "matches": [
            {"ts": "1606939916.452200", "channel": {"id": "D01OWNER", "is_im": True}},
            {"ts": "1606940000.000100", "channel": {"id": "G01PRIVATE", "is_private": True}},
            {"ts": "1606950000.000200", "channel": {"id": "C75M7C0SY", "name": "welcome"}},
        ],
    }
    row = member_history.history_row("U1", messages)
    assert row == ("U1", 4, epoch(1606950000.0002), "C75M7C0SY")


def test_history_row_without_public_match_returns_none_first_post():
    messages = {
        "total": 2,
        "matches": [
            {"ts": "1606939916.452200", "channel": {"id": "D01OWNER", "is_im": True}},
            {"ts": "1606940000.000100", "channel": {"id": "G01GROUP", "is_mpim": True}},
        ],
    }
    assert member_history.history_row("U1", messages) == ("U1", 2, None, None)


def test_joined_channels_filters_public_channels_and_dedupes():
    channels = [
        {"id": "C2", "is_channel": True},
        {"id": "C1", "is_channel": True},
        {"id": "C1", "is_channel": True},
        {"id": "C9", "is_channel": True, "is_private": True},
        {"id": "C8", "is_channel": True, "is_archived": True},
        {"id": "D1", "is_im": True},
    ]
    assert member_channels.joined_channels(channels) == ["C1", "C2"]


def test_range_row_with_span_source_sets_span_source():
    rec = {"channel_id": "C1", "messages_count": 5}
    row = channel_range_pull.range_row(
        rec, WINDOW_START, WINDOW_END, channel_range_pull.SPAN_SOURCE
    )

    assert row[3] == "admin_analytics_channel_span"
    assert row[3] != channel_range_pull.SOURCE


def test_range_row_default_source_is_range_source():
    rec = {"channel_id": "C1", "messages_count": 5}

    assert channel_range_pull.range_row(rec, WINDOW_START, WINDOW_END)[3] == (
        "admin_analytics_channel_range"
    )


def test_derived_flags_exclude_text():
    flags = shaping.derived("does anyone know how <@U123> fixed https://x.com ?")

    assert flags["is_question"] is True
    assert flags["has_link"] is True
    assert flags["mention_count"] == 1
    assert flags["emoji_only"] is False
    assert "text" not in flags
    assert all(not isinstance(v, str) for v in flags.values())


def test_derived_emoji_only_text_sets_emoji_only():
    assert shaping.derived(":tada: :rocket:")["emoji_only"] is True
    assert shaping.derived("nice :tada:")["emoji_only"] is False
    assert shaping.derived("")["emoji_only"] is False


def test_derived_substantive_threshold_at_80_characters():
    assert shaping.derived("x" * 79)["is_substantive"] is False
    assert shaping.derived("x" * 80)["is_substantive"] is True





def test_thread_row_without_replies_returns_none():
    assert channel_history_pull.thread_row("C1", {"ts": "1.0"}) is None
    assert channel_history_pull.thread_row("C1", {"ts": "1.0", "reply_count": 0}) is None
    assert channel_history_pull.thread_row("C1", {"ts": "1.0", "reply_count": 2})[2] == 2


def test_normalize_counts_content_fields_and_drops_redacted_keys():
    normalized = shaping.normalize({
        "ts": "1.0", "user": "U1", "text": "look <@U9> https://x.com ?",
        "blocks": [{"type": "rich_text"}, {"type": "divider"}],
        "attachments": [{"id": 1}],
        "files": [{"id": "F1"}, {"id": "F2"}],
        "reactions": [{"name": "tada", "count": 2, "users": ["U1", "U2"]},
                      {"name": "eyes", "count": 1, "users": ["U2"]}],
    })

    assert normalized["text_length"] == len("look <@U9> https://x.com ?")
    assert normalized["has_text"] is True
    assert normalized["block_count"] == 2
    assert normalized["attachment_count"] == 1
    assert normalized["file_count"] == 2
    assert normalized["reaction_count"] == 3
    assert normalized["reactor_count"] == 2
    assert normalized["mentioned_ids"] == ["U9"]
    assert all(k not in normalized for k in shaping.REDACT)


def test_normalize_message_without_content_returns_zero_counts():
    normalized = shaping.normalize({"ts": "1.0"})

    assert normalized["text_length"] == 0
    assert normalized["has_text"] is False
    assert normalized["block_count"] == 0
    assert normalized["file_count"] == 0
    assert normalized["reaction_count"] == 0
    assert normalized["mentioned_ids"] == []


def test_redact_removes_redacted_keys_at_any_depth():
    redacted = shaping.redact({
        "type": "message", "ts": "1.0", "text": "secret",
        "blocks": [{"text": {"text": "secret"}}],
        "files": [{"url_private": "https://files/x"}],
        "attachments": [{"fallback": "secret"}],
        "previous_message": {"text": "older secret"},
        "edited": {"user": "U1", "ts": "2.0"},
        "reactions": [{"name": "tada", "count": 1, "users": ["U1"]}],
    })

    assert set(redacted) == {"type", "ts", "edited", "reactions"}
    assert "secret" not in repr(redacted)
    assert redacted["edited"] == {"user": "U1", "ts": "2.0"}


def test_redact_channel_purpose_event_removes_all_free_text():
    sentinel = "WORDSOMEBODYWROTE"
    event = {
        "type": "message", "subtype": "channel_purpose", "ts": "1.0", "user": "U1",
        "text": sentinel,
        "blocks": [{"elements": [{"text": sentinel}]}],
        "attachments": [{"fallback": sentinel, "title": sentinel, "text": sentinel,
                         "pretext": sentinel, "footer": sentinel, "title_link": sentinel}],
        "files": [{"id": "F1", "name": f"{sentinel}.png", "title": sentinel,
                   "url_private": f"https://files.slack.com/{sentinel}", "preview": sentinel}],
        "message": {"ts": "1.0", "user": "U1", "text": sentinel, "purpose": sentinel,
                    "edited": {"user": "U1", "ts": "2.0"}, "reply_count": 2},
        "previous_message": {"text": sentinel},
        "root": {"ts": "0.9", "text": sentinel, "reply_count": 4},
        "user_profile": {"real_name": sentinel, "display_name": sentinel},
        "bot_profile": {"name": sentinel},
        "profile": {"email": sentinel},
        "purpose": sentinel, "topic": sentinel, "comment": {"comment": sentinel},
        "permalink": f"https://hackclub.slack.com/{sentinel}",
        "canvas": {"title": sentinel}, "huddle": {"title": sentinel},
        "reactions": [{"name": "tada", "count": 1, "users": ["U2"]}],
        "edited": {"user": "U1", "ts": "2.0"},
        "client_msg_id": "abc", "thread_ts": "1.0", "reply_count": 2, "team": "T1",
    }

    redacted = shaping.redact(event)

    assert sentinel not in json.dumps(redacted, default=str), "a field carrying words survived"
    assert redacted["reactions"] == [{"name": "tada", "count": 1, "users": ["U2"]}]
    assert redacted["message"] == {"ts": "1.0", "user": "U1", "reply_count": 2,
                                   "edited": {"user": "U1", "ts": "2.0"}}
    assert redacted["root"] == {"ts": "0.9", "reply_count": 4}


def test_redact_message_changed_keeps_metadata_without_text():
    redacted = shaping.redact({
        "type": "message", "subtype": "message_changed", "ts": "2.0",
        "message": {"ts": "1.0", "user": "U1", "text": "the new words",
                    "blocks": [{"text": "the new words"}], "files": [{"id": "F1"}],
                    "edited": {"user": "U1", "ts": "2.0"}, "reply_count": 2},
        "previous_message": {"ts": "1.0", "text": "the old words"},
    })

    assert "previous_message" not in redacted, "the pre-edit version has nothing to add"
    assert set(redacted["message"]) == {"ts", "user", "edited", "reply_count"}
    assert "words" not in repr(redacted)


def test_redact_user_object_keeps_id_team_and_bot_flag():
    redacted = shaping.redact({
        "type": "team_join",
        "user": {"id": "U1", "team_id": "T1", "is_bot": False,
                 "real_name": "a person", "profile": {"email": "a@b.c"}},
    })

    assert redacted["user"] == {"id": "U1", "team_id": "T1", "is_bot": False}


def test_author_kind_classifies_member_bot_and_unknown():
    assert shaping.author_kind({"user": "U1"}) == "member"
    assert shaping.author_kind({"bot_id": "B1"}) == "bot"
    assert shaping.author_kind({"user": "U1", "subtype": "bot_message"}) == "bot"
    assert shaping.author_kind({}) == "unknown"
