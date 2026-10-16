import datetime as dt

from bot.nemo import record

EXPIRES_AT = dt.datetime(2026, 3, 10, 23, 59, 59, tzinfo=dt.UTC)


def standing_row(**over):
    row = {"kind": "shush", "expires_at": EXPIRES_AT, "channel_id": None,
           "case_id": 412, "enforcement_status": "held", "enforced_by": "nemo"}
    row.update(over)
    return row


def test_in_force_line_no_guard_returns_nothing_active():
    assert record.in_force_line(None) == "nothing active"


def test_in_force_line_held_shush_includes_end_date():
    assert record.in_force_line(standing_row()) == "shush until 10 Mar"


def test_in_force_line_channel_ban_includes_channel_mention():
    line = record.in_force_line(standing_row(kind="channel_ban", channel_id="C1"))
    assert line == "channel ban in <#C1> until 10 Mar"


def test_in_force_line_without_expiry_says_no_end_date():
    assert record.in_force_line(standing_row(expires_at=None)) == "shush, no end date"


def test_in_force_line_pending_status_ends_with_pending():
    assert record.in_force_line(standing_row(enforcement_status="pending")).endswith(", pending")


def test_in_force_line_failed_status_ends_with_not_enforced():
    assert record.in_force_line(standing_row(enforcement_status="failed")).endswith(", not enforced")


def test_in_force_line_by_hand_guard_ends_with_manual():
    line = record.in_force_line(standing_row(enforced_by="by_hand", enforcement_status="held"))
    assert line.endswith(", manual")
    assert "not enforced" not in line


def test_in_force_sql_reads_member_guards_not_actions():
    assert "fd.member_guards" in record.IN_FORCE
    assert "fd.actions" not in record.IN_FORCE
    assert "state IN ('live', 'lifting')" in record.IN_FORCE


def test_counts_sql_counts_live_and_lifting_guards():
    assert "FROM fd.member_guards" in record.COUNTS
    assert "state IN ('live', 'lifting')) AS active_guard_count" in record.COUNTS


def test_format_counts_labels_each_count():
    line = record.format_counts({"subject_case_count": 1, "case_count": 2, "active_guard_count": 1, "reversed_action_count": 0})
    assert line == "1 as subject  ·  2 cases  ·  1 active"
    assert record.format_counts({"subject_case_count": 1, "case_count": 1, "active_guard_count": 0, "reversed_action_count": 2}) == (
        "1 as subject  ·  1 case  ·  0 active  ·  2 reversed")
    assert "action" not in line
