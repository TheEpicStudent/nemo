import datetime as dt

import pytest

from bot.nemo import command

USER_ID = "U1ABC"
CHANNEL_ID = "C1LOUNGE"
USER_MENTION = f"<@{USER_ID}|somebody>"
CHANNEL_MENTION = f"<#{CHANNEL_ID}|lounge>"


def test_shush_is_asked_for_like_the_other_verbs():
    verb, target, body = command.parse_command(f"shush {USER_MENTION} 3d flooding the channel")

    assert (verb, target, body) == (command.SHUSH, USER_ID, "3d flooding the channel")


def test_shush_needs_the_member_guard_capability():
    assert command.NEEDED[command.SHUSH] == "member.guard"


NOW = dt.datetime(2026, 10, 16, 9, 30, tzinfo=dt.UTC)


@pytest.mark.parametrize(("text", "length"), [
    ("30m", dt.timedelta(minutes=30)),
    ("2h", dt.timedelta(hours=2)),
    ("3d", dt.timedelta(days=3)),
    ("2w", dt.timedelta(weeks=2)),
    ("1D", dt.timedelta(days=1)),
])
def test_ends_at_length_adds_to_now(text, length):
    assert command.ends_at(text, NOW) == NOW + length


def test_ends_at_date_ends_at_end_of_day():
    assert command.ends_at("2026-11-20", NOW) == dt.datetime(2026, 11, 20, 23, 59, 59, tzinfo=dt.UTC)


@pytest.mark.parametrize("text", ["0m", "366d", "53w", "soon", "", "-3d", "2026-13-01",
                                  "2026-10-16", "2026-10-15", "2027-12-01"])
def test_ends_at_out_of_range_reads_as_none(text):
    assert command.ends_at(text, NOW) is None


def test_for_how_long_splits_length_off_reason():
    assert command.for_how_long("2w  flooding   #lounge", NOW) == \
        (True, NOW + dt.timedelta(weeks=2), "flooding #lounge")


def test_for_how_long_without_length_has_no_end():
    assert command.for_how_long("flooding the channel", NOW) == (True, None, "flooding the channel")


def test_for_how_long_reason_starting_with_number_has_no_end():
    assert command.for_how_long("3 spam messages", NOW) == (True, None, "3 spam messages")


def test_for_how_long_bad_length_is_invalid():
    assert command.for_how_long("400d spamming", NOW) == (False, None, "spamming")


def test_for_how_long_length_without_reason_has_no_reason():
    assert command.for_how_long("3d", NOW) == (True, NOW + dt.timedelta(days=3), None)


def test_shushed_with_no_end_says_so():
    assert command.shushed("U1", None, "spamming") == \
        "<@U1> has been shushed with no end date. Reason: spamming"


def test_banned_with_time_shows_utc_time():
    assert command.banned("U1", "C1", dt.datetime(2026, 10, 16, 11, 30, tzinfo=dt.UTC), "spamming") == \
        "<@U1> has been banned from <#C1> until 16 Oct, 11:30 UTC. Reason: spamming"


def test_channelban_is_asked_for_like_the_other_verbs():
    verb, target, body = command.parse_command(f"channelban {USER_MENTION} {CHANNEL_MENTION} 3d flooding it")

    assert (verb, target, body) == (command.CHANNEL_BAN, USER_ID, f"{CHANNEL_MENTION} 3d flooding it")


def test_channelban_needs_the_member_guard_capability():
    assert command.NEEDED[command.CHANNEL_BAN] == "member.guard"


def test_the_channel_is_split_off_wherever_it_was_said():
    assert command.in_a_channel(f"{CHANNEL_MENTION} 3d flooding it") == (CHANNEL_ID, "3d flooding it")
    assert command.in_a_channel(f"3d flooding {CHANNEL_MENTION}") == (CHANNEL_ID, "3d flooding")


def test_a_ban_with_no_channel_is_held_back():
    assert command.in_a_channel("3d flooding it") == (None, None)
    assert command.in_a_channel("3d flooding #lounge") == (None, None)


def test_the_length_still_reads_after_the_channel_comes_out():
    channel_id, remainder = command.in_a_channel(f"{CHANNEL_MENTION} 2w flooding it")

    assert channel_id == CHANNEL_ID
    assert command.for_how_long(remainder, NOW) == (True, NOW + dt.timedelta(weeks=2), "flooding it")


def test_the_help_card_lists_shush_only_for_who_holds_it():
    help_text = command.helping.flat({"member.guard"})

    assert "/nemo shush" in help_text
    assert "/nemo channelban" in help_text
    assert "/nemo shush" not in command.helping.flat({"case.read"})


REPORT_CASE = "JOIN fd.case_reports r ON r.case_id = c.id"
QUEUE_CASE = "SELECT id, category_key"
OPENING = "mirrored_as = 'card'"
ACTION_COUNT = "FROM fd.actions"


class Conn:
    def __init__(self, rows):
        self.rows = rows
        self.last_sql = ""

    def execute(self, sql, args=None):
        self.last_sql = sql
        return self

    def fetchone(self):
        for marker, row in self.rows.items():
            if marker in self.last_sql:
                return row
        return None

    def fetchall(self):
        return []


def queue_case_row(case_id):
    return (case_id, None, None, "C_FIRE", "5.5", None, "UOPENER", None, None, None)


def report_case_row(case_id, body):
    return (case_id, None, None, 3, True, None, body, "1.1", None, None, None, None, "C_FIRE",
            None)


def test_case_answer_falls_back_to_the_queue_card():
    conn = Conn({QUEUE_CASE: queue_case_row(12), OPENING: (7, "spam in the lounge")})

    answer = command.case_answer(conn, 12)

    assert answer["text"] == "case 12"
    assert "spam in the lounge" in str(answer["blocks"])


def test_case_answer_without_an_opening_shows_the_header():
    answer = command.case_answer(Conn({QUEUE_CASE: queue_case_row(12)}), 12)

    assert "Case 12" in str(answer["blocks"])


def test_case_answer_keeps_the_report_quote():
    conn = Conn({REPORT_CASE: report_case_row(12, "they spammed"), ACTION_COUNT: (0,)})

    answer = command.case_answer(conn, 12)

    assert "they spammed" in str(answer["blocks"])


def test_case_answer_for_an_unknown_number():
    assert command.case_answer(Conn({}), 99)["text"] == "There is no case 99."
