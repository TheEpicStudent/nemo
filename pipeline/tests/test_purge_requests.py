from contextlib import contextmanager

import pytest
from psycopg import errors

from bot.core import audit
from bot.nemo import command, purge_requests
from bot.nemo.views import help as helping

MEMBER = "U07ABCDEF"
HERE = "C01HERE"
LOUNGE = "C09LOUNGE"


def asked(text, here=HERE):
    verb, target, body = command.parse_command(f"purge {text}".strip())
    assert verb == command.PURGE
    return purge_requests.requested(target, body, here)


def test_a_number_alone_purges_this_channel():
    request, problem = asked("50")

    assert problem is None
    assert request == purge_requests.Request(HERE, None, 50, None)


def test_the_channel_and_number_read_in_either_order():
    assert asked(f"<#{LOUNGE}|lounge> 50")[0] == purge_requests.Request(LOUNGE, None, 50, None)
    assert asked(f"50 <#{LOUNGE}|lounge>")[0] == purge_requests.Request(LOUNGE, None, 50, None)


def test_a_private_channel_with_no_name_still_reads():
    assert asked("25 <#G01SECRET|>")[0].channel_id == "G01SECRET"


def test_a_whole_channel_cannot_be_asked_for():
    assert asked(f"<#{LOUNGE}|lounge>") == (None, purge_requests.NEED_A_NUMBER)
    assert asked(f"<#{LOUNGE}|lounge> raid") == (None, purge_requests.NEED_A_NUMBER)


def test_a_member_in_a_channel_with_no_number_means_all_of_theirs_there():
    assert asked(f"<@{MEMBER}> <#{LOUNGE}|lounge>")[0] == purge_requests.Request(
        LOUNGE, MEMBER, None, None)


def test_a_member_alone_means_every_message_in_every_channel():
    assert asked(f"<@{MEMBER}|them>")[0] == purge_requests.Request(None, MEMBER, None, None)


def test_a_member_with_a_number_means_their_last_few_everywhere():
    assert asked(f"<@{MEMBER}> 30")[0] == purge_requests.Request(None, MEMBER, 30, None)


def test_a_member_in_a_channel_reads_in_any_order_with_a_reason():
    request, _ = asked(f"40 <#{LOUNGE}|lounge> <@{MEMBER}|them> raid on friday")

    assert request == purge_requests.Request(LOUNGE, MEMBER, 40, "raid on friday")


def test_nothing_at_all_asks_what_to_purge():
    assert asked("") == (None, purge_requests.USAGE)


def test_a_number_in_a_direct_message_needs_a_channel_named():
    assert asked("50", here="D01DIRECT") == (None, purge_requests.NAME_A_CHANNEL)


def test_a_number_out_of_range_is_refused():
    assert asked("0") == (None, purge_requests.OUT_OF_RANGE)
    assert asked("10001") == (None, purge_requests.OUT_OF_RANGE)


def test_a_reason_that_runs_on_is_refused():
    assert asked("50 " + "a" * 501) == (None, purge_requests.TOO_LONG)


def test_each_kind_needs_its_own_capability():
    assert purge_requests.needed(MEMBER) == "member.purge"
    assert purge_requests.needed(None) == "channel.purge"


def test_the_confirm_says_what_goes():
    request = purge_requests.Request

    assert (purge_requests.described(request(HERE, None, 50, None))
            == f"the last 50 messages in <#{HERE}>, with their thread replies")
    assert (purge_requests.described(request(None, MEMBER, None, None), 1204)
            == f"all 1,204 messages from <@{MEMBER}> in every channel")
    assert (purge_requests.described(request(LOUNGE, MEMBER, 1, None))
            == f"the last 1 message from <@{MEMBER}> in <#{LOUNGE}>")
    assert (purge_requests.described(request(LOUNGE, MEMBER, None, None), 25000)
            == f"the last 10,000 of 25,000 messages from <@{MEMBER}> in <#{LOUNGE}>")
    assert (purge_requests.described(request(None, MEMBER, None, None), 0)
            == f"every message from <@{MEMBER}> in every channel")


def test_the_prompt_carries_a_danger_button_and_a_cancel():
    built = purge_requests.prompt(12, purge_requests.Request(HERE, None, 50, "spam wave"), None)
    buttons = built["blocks"][-1]["elements"]

    assert built["text"].startswith("Confirm purging the last 50 messages")
    assert built["blocks"][1]["elements"][0]["text"] == "Reason: spam wave"
    assert [(one["action_id"], one["value"], one.get("style")) for one in buttons] == [
        (purge_requests.CONFIRM, "12", "danger"), (purge_requests.CANCEL, "12", None)]


class Conn:
    def __init__(self, row, unique_clash=False):
        self.row = row
        self.unique_clash = unique_clash
        self.executed = []
        self.result = None

    def execute(self, sql, args=None):
        self.executed.append(sql)
        if sql == purge_requests.QUEUED and self.unique_clash:
            raise errors.UniqueViolation("purges_one_waiting")
        self.result = self.row if sql == purge_requests.PROPOSED else None
        return self

    def fetchone(self):
        return self.result

    @contextmanager
    def transaction(self):
        yield


@pytest.fixture
def stub(monkeypatch):
    state = {"allowed": (True, None), "conn": None}

    @contextmanager
    def session():
        yield state["conn"]

    monkeypatch.setattr(purge_requests, "session", session)
    monkeypatch.setattr(purge_requests.access, "may",
                        lambda conn, user_id, key, case_id=None: state["allowed"])
    monkeypatch.setattr(purge_requests.channel, "internal_log_channel", lambda: "CLOG")
    return state


def proposal(asked_by="UME", fresh=True, member_id=None):
    return (HERE, member_id, 50, None, asked_by, fresh)


def test_confirming_queues_it_and_says_where_the_result_goes(stub):
    stub["conn"] = Conn(proposal())

    answer = purge_requests.confirm(12, "UME")
    assert answer == (f"Purging the last 50 messages in <#{HERE}>, with their thread replies. "
                      "Nemo posts the result in <#CLOG>.")
    assert purge_requests.QUEUED in stub["conn"].executed
    assert audit.RECORD in stub["conn"].executed


def test_only_the_asker_can_confirm(stub):
    stub["conn"] = Conn(proposal(asked_by="USOMEONE"))

    assert purge_requests.confirm(12, "UME") == "Only <@USOMEONE> can confirm this purge."
    assert purge_requests.QUEUED not in stub["conn"].executed


def test_a_confirm_that_ran_out_is_dropped(stub):
    stub["conn"] = Conn(proposal(fresh=False))

    assert purge_requests.confirm(12, "UME") == purge_requests.EXPIRED
    assert purge_requests.DROP in stub["conn"].executed


def test_a_confirm_after_losing_the_right_is_refused(stub):
    stub["conn"] = Conn(proposal())
    stub["allowed"] = (False, "member purge is Community manager only")

    assert purge_requests.confirm(12, "UME") == "member purge is Community manager only"
    assert purge_requests.QUEUED not in stub["conn"].executed


def test_a_second_purge_on_the_same_target_is_refused(stub):
    stub["conn"] = Conn(proposal(), unique_clash=True)

    assert purge_requests.confirm(12, "UME") == purge_requests.ALREADY_RUNNING
    assert purge_requests.DROP in stub["conn"].executed


def test_a_confirm_that_is_gone_says_so(stub):
    stub["conn"] = Conn(None)

    assert purge_requests.confirm(12, "UME") == purge_requests.GONE


def test_only_the_asker_can_cancel(stub):
    stub["conn"] = Conn(proposal(asked_by="USOMEONE"))
    assert purge_requests.cancel(12, "UME") is False

    stub["conn"] = Conn(proposal())
    assert purge_requests.cancel(12, "UME") is True


def test_the_button_value_is_read_back_as_the_purge():
    assert command.chosen({"actions": [{"value": "12"}]}) == 12
    assert command.chosen({"actions": [{"value": "nope"}]}) == 0
    assert command.chosen({}) == 0


def test_help_lists_purging_only_for_who_may():
    nobody = helping.build_blocks({"case.read"})
    channel_only = helping.build_blocks({"channel.purge"})
    text = str(channel_only)

    assert "/nemo purge" not in str(nobody)
    assert "/nemo purge #channel 50" in text
    assert "/nemo purge @somebody" not in text
