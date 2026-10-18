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


def test_active_line_capitalises_and_names_case():
    assert record.active_line(standing_row()) == "Shush until 10 Mar, case 412"


def test_active_line_without_case_has_no_case_suffix():
    assert record.active_line(standing_row(case_id=None)) == "Shush until 10 Mar"


def test_active_line_no_guard_returns_nothing_active():
    assert record.active_line(None) == "Nothing active"


def counts(**over):
    row = {"case_count": 0, "open_case_count": 0, "action_count": 0, "reversed_action_count": 0, "note_count": 0}
    row.update(over)
    return row


def test_counts_line_labels_each_count():
    line = record.counts_line(counts(case_count=9, open_case_count=1, action_count=3, reversed_action_count=1, note_count=1))

    assert line == "9 cases, 1 open, 3 actions, 1 reversed, 1 note"


def test_counts_line_singular_and_zero_parts_omitted():
    assert record.counts_line(counts(case_count=1, action_count=1)) == "1 case, 1 action"


def test_counts_line_without_record_says_no_record():
    assert record.counts_line(counts()) == "No record"


def test_counts_line_notes_only():
    assert record.counts_line(counts(note_count=2)) == "2 notes"
