import datetime as dt

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


def test_days_and_weeks_both_read_as_a_date():
    today = dt.date.today()

    assert command.ends_on("3d") == today + dt.timedelta(days=3)
    assert command.ends_on("2w") == today + dt.timedelta(days=14)
    assert command.ends_on("1D") == today + dt.timedelta(days=1)


def test_a_date_is_taken_as_it_stands():
    expires_on = dt.date.today() + dt.timedelta(days=40)

    assert command.ends_on(expires_on.strftime("%Y-%m-%d")) == expires_on


def test_what_is_not_a_length_reads_as_none():
    for text in ("0d", "999d", "soon", "", "2026-13-01", "-3d"):
        assert command.ends_on(text) is None, text


def test_a_date_already_gone_reads_as_none():
    yesterday = dt.date.today() - dt.timedelta(days=1)

    assert command.ends_on(yesterday.strftime("%Y-%m-%d")) is None


def test_the_length_is_split_off_the_reason():
    expires_on, reason = command.for_how_long("2w  flooding   #lounge")

    assert expires_on == dt.date.today() + dt.timedelta(days=14)
    assert reason == "flooding #lounge"


def test_a_reason_with_no_length_is_held_back():
    assert command.for_how_long("flooding the channel") == (None, None)


def test_a_length_with_no_reason_leaves_nothing_to_write_down():
    expires_on, reason = command.for_how_long("3d")

    assert expires_on == dt.date.today() + dt.timedelta(days=3)
    assert reason is None


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
    expires_on, reason = command.for_how_long(remainder)

    assert channel_id == CHANNEL_ID
    assert expires_on == dt.date.today() + dt.timedelta(days=14)
    assert reason == "flooding it"


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
