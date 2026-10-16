from contextlib import contextmanager

import pytest
from psycopg import errors

from bot.core import audit
from bot.nemo import command, purge_requests
from bot.nemo.views import help as helping

MEMBER = "U07ABCDEF"
CURRENT_CHANNEL_ID = "C01HERE"
TARGET_CHANNEL_ID = "C09LOUNGE"


def parse_purge(text, current_channel_id=CURRENT_CHANNEL_ID):
    verb, target, body = command.parse_command(f"purge {text}".strip())
    assert verb == command.PURGE
    return purge_requests.parse_request(target, body, current_channel_id)


def test_parse_request_number_only_targets_current_channel():
    request, problem = parse_purge("50")

    assert problem is None
    assert request == purge_requests.Request(CURRENT_CHANNEL_ID, None, 50, None)


def test_parse_request_channel_and_number_in_either_order_match():
    assert parse_purge(f"<#{TARGET_CHANNEL_ID}|lounge> 50")[0] == purge_requests.Request(TARGET_CHANNEL_ID, None, 50, None)
    assert parse_purge(f"50 <#{TARGET_CHANNEL_ID}|lounge>")[0] == purge_requests.Request(TARGET_CHANNEL_ID, None, 50, None)


def test_parse_request_private_channel_without_name_returns_channel_id():
    assert parse_purge("25 <#G01SECRET|>")[0].channel_id == "G01SECRET"


def test_parse_request_channel_without_number_returns_need_a_number():
    assert parse_purge(f"<#{TARGET_CHANNEL_ID}|lounge>") == (None, purge_requests.NEED_A_NUMBER)
    assert parse_purge(f"<#{TARGET_CHANNEL_ID}|lounge> raid") == (None, purge_requests.NEED_A_NUMBER)


def test_parse_request_member_and_channel_without_number_targets_member_in_channel():
    assert parse_purge(f"<@{MEMBER}> <#{TARGET_CHANNEL_ID}|lounge>")[0] == purge_requests.Request(
        TARGET_CHANNEL_ID, MEMBER, None, None)


def test_parse_request_member_only_targets_all_channels():
    assert parse_purge(f"<@{MEMBER}|them>")[0] == purge_requests.Request(None, MEMBER, None, None)


def test_parse_request_member_and_number_targets_last_n_in_all_channels():
    assert parse_purge(f"<@{MEMBER}> 30")[0] == purge_requests.Request(None, MEMBER, 30, None)


def test_parse_request_member_channel_number_and_reason_in_any_order():
    request, _ = parse_purge(f"40 <#{TARGET_CHANNEL_ID}|lounge> <@{MEMBER}|them> raid on friday")

    assert request == purge_requests.Request(TARGET_CHANNEL_ID, MEMBER, 40, "raid on friday")


def test_parse_request_empty_input_returns_usage():
    assert parse_purge("") == (None, purge_requests.USAGE)


def test_parse_request_number_in_direct_message_returns_name_a_channel():
    assert parse_purge("50", current_channel_id="D01DIRECT") == (None, purge_requests.NAME_A_CHANNEL)


def test_parse_request_number_out_of_range_returns_out_of_range():
    assert parse_purge("0") == (None, purge_requests.OUT_OF_RANGE)
    assert parse_purge("10001") == (None, purge_requests.OUT_OF_RANGE)


def test_parse_request_reason_over_500_chars_returns_too_long():
    assert parse_purge("50 " + "a" * 501) == (None, purge_requests.TOO_LONG)


def test_capability_for_member_returns_member_purge_and_none_returns_channel_purge():
    assert purge_requests.capability_for(MEMBER) == "member.purge"
    assert purge_requests.capability_for(None) == "channel.purge"


def test_describe_request_returns_scope_text_for_each_target():
    request = purge_requests.Request

    assert (purge_requests.describe(request(CURRENT_CHANNEL_ID, None, 50, None))
            == f"the last 50 messages in <#{CURRENT_CHANNEL_ID}>, with their thread replies")
    assert (purge_requests.describe(request(None, MEMBER, None, None), 1204)
            == f"all 1,204 messages from <@{MEMBER}> in every channel")
    assert (purge_requests.describe(request(TARGET_CHANNEL_ID, MEMBER, 1, None))
            == f"the last 1 message from <@{MEMBER}> in <#{TARGET_CHANNEL_ID}>")
    assert (purge_requests.describe(request(TARGET_CHANNEL_ID, MEMBER, None, None), 25000)
            == f"the last 10,000 of 25,000 messages from <@{MEMBER}> in <#{TARGET_CHANNEL_ID}>")
    assert (purge_requests.describe(request(None, MEMBER, None, None), 0)
            == f"every message from <@{MEMBER}> in every channel")


def test_prompt_returns_confirm_danger_button_and_cancel_button():
    message = purge_requests.prompt(12, purge_requests.Request(CURRENT_CHANNEL_ID, None, 50, "spam wave"), None)
    buttons = message["blocks"][-1]["elements"]

    assert message["text"].startswith("Confirm purging the last 50 messages")
    assert message["blocks"][1]["elements"][0]["text"] == "Reason: spam wave"
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
        if sql == purge_requests.MARK_QUEUED and self.unique_clash:
            raise errors.UniqueViolation("purges_one_waiting")
        self.result = self.row if sql == purge_requests.PROPOSAL else None
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
    monkeypatch.setattr(purge_requests.channel, "log_channel", lambda: "CLOG")
    return state


def proposal(asked_by="UME", fresh=True, member_id=None):
    return (CURRENT_CHANNEL_ID, member_id, 50, None, asked_by, fresh)


def test_confirm_by_requester_marks_queued_records_audit_and_returns_summary(stub):
    stub["conn"] = Conn(proposal())

    answer = purge_requests.confirm(12, "UME")
    assert answer == (f"Purging the last 50 messages in <#{CURRENT_CHANNEL_ID}>, with their thread replies "
                      "· Result in <#CLOG>")
    assert purge_requests.MARK_QUEUED in stub["conn"].executed
    assert audit.RECORD in stub["conn"].executed


def test_confirm_by_other_user_returns_requester_only_message(stub):
    stub["conn"] = Conn(proposal(asked_by="USOMEONE"))

    assert purge_requests.confirm(12, "UME") == "Only <@USOMEONE> can confirm"
    assert purge_requests.MARK_QUEUED not in stub["conn"].executed


def test_confirm_expired_proposal_returns_expired_and_deletes_proposal(stub):
    stub["conn"] = Conn(proposal(fresh=False))

    assert purge_requests.confirm(12, "UME") == purge_requests.EXPIRED
    assert purge_requests.DELETE_PROPOSAL in stub["conn"].executed


def test_confirm_without_capability_returns_denial_and_does_not_queue(stub):
    stub["conn"] = Conn(proposal())
    stub["allowed"] = (False, "member purge is Community manager only")

    assert purge_requests.confirm(12, "UME") == "member purge is Community manager only"
    assert purge_requests.MARK_QUEUED not in stub["conn"].executed


def test_confirm_unique_violation_returns_already_running_and_deletes_proposal(stub):
    stub["conn"] = Conn(proposal(), unique_clash=True)

    assert purge_requests.confirm(12, "UME") == purge_requests.ALREADY_RUNNING
    assert purge_requests.DELETE_PROPOSAL in stub["conn"].executed


def test_confirm_missing_proposal_returns_not_found(stub):
    stub["conn"] = Conn(None)

    assert purge_requests.confirm(12, "UME") == purge_requests.NOT_FOUND


def test_cancel_by_other_user_returns_false_and_by_requester_returns_true(stub):
    stub["conn"] = Conn(proposal(asked_by="USOMEONE"))
    assert purge_requests.cancel(12, "UME") is False

    stub["conn"] = Conn(proposal())
    assert purge_requests.cancel(12, "UME") is True


def test_button_value_parses_action_value_and_defaults_to_zero():
    assert command.button_value({"actions": [{"value": "12"}]}) == 12
    assert command.button_value({"actions": [{"value": "nope"}]}) == 0
    assert command.button_value({}) == 0


def test_build_blocks_lists_purge_only_with_channel_purge_capability():
    read_only_blocks = helping.build_blocks({"case.read"})
    channel_only = helping.build_blocks({"channel.purge"})
    text = str(channel_only)

    assert "/nemo purge" not in str(read_only_blocks)
    assert "/nemo purge #channel 50" in text
    assert "/nemo purge @somebody" not in text
