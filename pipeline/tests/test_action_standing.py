import datetime as dt

from bot.nemo import memberguards
from bot.nemo.views import action

CHANNEL_ID = "C1"
USER_ID = "U1"
MOD = "UMOD"
OPENED_AT = dt.datetime(2026, 3, 3, 12, tzinfo=dt.UTC)
EXPIRES_AT = dt.datetime(2026, 3, 10, 12, tzinfo=dt.UTC)


class Conn:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None


def guard(**over):
    row = {
        "id": 7, "kind": "shush", "subject_id": USER_ID, "channel_id": None,
        "state": "live", "enforcement_status": "held", "enforced_by": "nemo", "case_id": None,
        "opened_by": MOD, "opened_at": OPENED_AT, "reason": "being awful",
        "expires_at": EXPIRES_AT,
    }
    row.update(over)
    return row


def ids(built):
    return [one.get("block_id") for one in built]


def words(built):
    parts = []
    for one in built:
        if one.get("type") == "section":
            parts.append(one["text"]["text"])
        if one.get("type") == "context":
            parts += [item.get("text", "") for item in one["elements"]]
    return "\n".join(parts)


def standing(guard_row, case_id=412, enforceable=True):
    return {"enforceable": enforceable, "guard": guard_row, "case_id": case_id,
            "reads": memberguards.reads(guard_row, case_id)}


def test_a_modal_with_nothing_standing_grows_no_warning():
    built = action.build_blocks(412, {"type_key": "shush", "target_user_id": USER_ID},
                          standing(None))
    assert action.GUARD_STATUS not in ids(built)


def test_a_record_only_kind_never_grows_a_warning():
    built = action.build_blocks(412, {"type_key": "warning", "target_user_id": USER_ID}, None)
    assert action.GUARD_STATUS not in ids(built)


def submission(**over):
    row = {"type_key": "warning", "target_user_id": USER_ID,
           "reason": "kept at it after being asked to stop"}
    row.update(over)
    return row


def test_echo_blocks_names_the_action_and_who_it_is_against():
    built = action.echo_blocks(submission(), MOD)
    assert built[0] == {"type": "header", "text": {"type": "plain_text", "text": "Warning"}}
    assert built[1]["elements"][0]["text"] == f"Against <@{USER_ID}> · logged by <@{MOD}>"
    assert built[2] == {"type": "divider"}


def test_echo_blocks_quotes_the_reason():
    built = action.echo_blocks(submission(), MOD)
    quoted = next(one for one in built if one["type"] == "section")
    assert quoted["text"]["text"] == "> kept at it after being asked to stop"


def test_the_header_names_a_channel_ban_its_channel_and_its_end_date():
    built = action.echo_blocks(
        submission(type_key="channel_ban", channel_id="CGEN", expires_on="2026-03-10"), MOD,
        channel_name="general",
    )
    assert built[0]["text"]["text"] == "Channel ban from #general until 10 Mar"


def test_a_channel_ban_falls_back_to_the_raw_id_when_the_name_is_unknown():
    built = action.echo_blocks(
        submission(type_key="channel_ban", channel_id="CGEN", expires_on="2026-03-10"), MOD,
    )
    assert built[0]["text"]["text"] == "Channel ban from CGEN until 10 Mar"


def test_a_shush_names_its_end_date_but_no_channel():
    built = action.echo_blocks(submission(type_key="shush", expires_on="2026-03-10"), MOD)
    assert built[0]["text"]["text"] == "Shush until 10 Mar"


def test_a_temporary_ban_names_its_end_date():
    built = action.echo_blocks(submission(type_key="temp_ban", expires_on="2026-03-10"), MOD)
    assert built[0]["text"]["text"] == "Temporary ban until 10 Mar"


def test_a_permanent_ban_has_no_end_date_to_name():
    built = action.echo_blocks(submission(type_key="perma_ban"), MOD)
    assert built[0]["text"]["text"] == "Permanent ban"


def test_echo_blocks_adds_a_resolution_note_only_when_given():
    without = action.echo_blocks(submission(), MOD)
    assert all(
        "Outcome" not in element.get("text", "")
        for block in without for element in block.get("elements", [])
    )

    blocks = action.echo_blocks(submission(resolution_note="walked them through the rules in a DM"), MOD)
    footer = blocks[-1]["elements"][0]["text"]
    assert footer == "*Outcome:* walked them through the rules in a DM"


def test_the_modal_always_offers_a_resolution_note():
    built = action.build_blocks(412, {"type_key": "shush", "target_user_id": USER_ID}, None)
    assert action.RESOLUTION_NOTE in ids(built)


def test_the_resolution_note_is_optional():
    built = action.build_blocks(412, {"type_key": "shush", "target_user_id": USER_ID}, None)
    field = next(one for one in built if one.get("block_id") == action.RESOLUTION_NOTE)
    assert field["optional"] is True


def test_the_resolution_note_sits_right_under_the_action_kind():
    built = action.build_blocks(412, {"type_key": "shush", "target_user_id": USER_ID}, None)
    block_ids = [one.get("block_id") for one in built]
    assert block_ids.index(action.KIND) + 1 == block_ids.index(action.RESOLUTION_NOTE)


def test_submitted_values_reads_and_strips_the_resolution_note():
    state = {"values": {action.RESOLUTION_NOTE: {action.RESOLUTION_NOTE: {
        "value": "  talked it through  "
    }}}}
    assert action.submitted_values(state)["resolution_note"] == "talked it through"


def test_an_orphaned_guard_says_it_has_no_case():
    built = action.build_blocks(412, {"type_key": "shush"}, standing(guard()))
    assert action.GUARD_STATUS in ids(built)
    text = words(built)
    assert f"<@{USER_ID}> already has an active shush with no case" in text
    assert f"set by <@{MOD}>" in text
    assert "since 3 Mar" in text
    assert "until 10 Mar" in text


def test_a_guard_on_another_case_names_that_case():
    built = action.build_blocks(412, {"type_key": "shush"}, standing(guard(case_id=318)))
    assert "on *case 318*" in words(built)


def test_a_guard_on_this_case_says_so():
    built = action.build_blocks(412, {"type_key": "shush"}, standing(guard(case_id=412)))
    assert "on this case" in words(built)


def test_a_channel_guard_names_its_channel():
    guard_row = guard(kind="channel_ban", channel_id=CHANNEL_ID)
    built = action.build_blocks(412, {"type_key": "channel_ban"}, standing(guard_row))
    assert f"channel ban in <#{CHANNEL_ID}>" in words(built)


def test_a_guard_with_no_end_date_says_that_instead():
    built = action.build_blocks(412, {"type_key": "shush"}, standing(guard(expires_at=None)))
    assert "no end date" in words(built)
    assert "until" not in words(built)


def test_a_pending_guard_says_pending():
    built = action.build_blocks(412, {"type_key": "shush"}, standing(guard(enforcement_status="pending")))
    assert "pending" in words(built)


def test_a_failed_guard_says_not_enforced():
    built = action.build_blocks(412, {"type_key": "shush"}, standing(guard(enforcement_status="failed")))
    assert "not enforced" in words(built)


def test_a_manual_guard_says_manual():
    guard_row = guard(enforced_by="by_hand", enforcement_status="held")
    text = words(action.build_blocks(412, {"type_key": "shush"}, standing(guard_row)))
    assert "manual" in text
    assert "not enforced" not in text


def test_the_warning_sits_above_the_date_it_is_about():
    built = action.build_blocks(412, {"type_key": "shush"}, standing(guard()))
    block_ids = ids(built)
    assert block_ids.index(action.GUARD_STATUS) < block_ids.index(action.UNTIL)


def test_who_what_and_where_all_reshape_the_modal():
    built = action.build_blocks(412, {"type_key": "channel_ban"}, None)
    blocks_by_id = {one.get("block_id"): one for one in built}
    assert blocks_by_id[action.TARGET]["dispatch_action"]
    assert blocks_by_id[action.KIND]["dispatch_action"]
    assert blocks_by_id[action.WHERE]["dispatch_action"]


def test_a_submit_that_never_saw_the_warning_is_sent_back():
    values = {"type_key": "shush", "target_user_id": USER_ID, "expires_on": "2026-03-10"}
    visible_blocks = {action.TARGET, action.KIND, action.UNTIL, action.REASON}
    assert action.requires_refresh(values, visible_blocks, standing(guard()))
    assert action.requires_refresh(values, visible_blocks | {action.SETTLE}, standing(guard()))
    assert not action.requires_refresh(
        values, visible_blocks | {action.GUARD_STATUS, action.SETTLE}, standing(guard())
    )


def test_an_enforceable_kind_with_nothing_standing_is_not_asked():
    values = {"type_key": "shush", "target_user_id": USER_ID, "expires_on": "2026-03-10"}
    visible_blocks = {action.TARGET, action.KIND, action.UNTIL, action.REASON}
    assert not action.requires_refresh(values, visible_blocks, standing(None))


def test_a_record_only_kind_goes_straight_through():
    values = {"type_key": "warning", "target_user_id": USER_ID}
    visible_blocks = {action.TARGET, action.KIND, action.REASON}
    assert not action.requires_refresh(values, visible_blocks, standing(None, enforceable=False))
    assert not action.requires_refresh(values, visible_blocks)


def test_settle_leaves_a_record_only_kind_alone():
    conn = Conn()
    result = memberguards.settle(conn, "warning", USER_ID, 412)
    assert result == {"enforceable": False, "guard": None,
                      "reads": memberguards.UNGUARDED, "case_id": 412}
    assert conn.executed == []


def test_settle_waits_until_somebody_is_named():
    conn = Conn()
    result = memberguards.settle(conn, "shush", None, 412)
    assert result["enforceable"]
    assert result["guard"] is None
    assert conn.executed == []


def test_settle_reads_what_it_finds_against_the_case_in_hand():
    row = tuple(guard(case_id=318)[field] for field in memberguards.FIELDS)
    result = memberguards.settle(Conn([row]), "shush", USER_ID, 412)
    assert result["reads"] == memberguards.ELSEWHERE
    assert result["guard"]["case_id"] == 318
