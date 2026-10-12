import pytest

from bot.nemo import memberguards
from bot.nemo.views import action

CHANNEL_ID = "C1"
USER_ID = "U1"


class Conn:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


def guard(**over):
    row = {
        "id": 7, "kind": "shush", "subject_id": USER_ID, "channel_id": None,
        "state": "live", "enforcement_status": "held", "enforced_by": "nemo", "case_id": None,
        "opened_by": "UMOD", "opened_at": None, "reason": "being awful",
        "expires_at": None,
    }
    row.update(over)
    return tuple(row[field] for field in memberguards.FIELDS)


def test_the_actions_table_says_which_kinds_nemo_can_carry():
    assert action.guard_kind("shush") == "shush"
    assert action.guard_scope("shush") == "workspace"
    assert action.guard_mode("shush") == "reactive"
    assert action.guard_kind("channel_ban") == "channel_ban"
    assert action.guard_scope("channel_ban") == "channel"


@pytest.mark.parametrize("type_key", ["warning", "locked_thread", "dm"])
def test_a_kind_without_an_enforce_block_is_a_record_only(type_key):
    assert action.guard_kind(type_key) is None
    assert action.enforce(type_key) == {}
    assert not memberguards.enforceable(type_key)


@pytest.mark.parametrize("type_key", ["temp_ban", "indef_ban", "perma_ban"])
def test_a_ban_is_carried_as_a_deactivation_on_the_account(type_key):
    assert action.guard_kind(type_key) == memberguards.DEACTIVATION
    assert action.guard_scope(type_key) == "account"
    assert action.guard_mode(type_key) == "applied"
    assert memberguards.enforceable(type_key)


def test_a_deactivation_is_never_looked_up_against_a_channel():
    conn = Conn([guard(kind=memberguards.DEACTIVATION)])
    memberguards.for_action(conn, "perma_ban", USER_ID, channel_id="C9")
    assert conn.executed[0][1] == (USER_ID, memberguards.DEACTIVATION, None)


def test_a_kind_nobody_declared_is_not_enforceable():
    assert action.guard_kind("nonsense") is None
    assert not memberguards.enforceable("nonsense")


def test_a_record_only_kind_is_never_looked_up():
    conn = Conn([guard()])
    assert memberguards.for_action(conn, "warning", USER_ID) is None
    assert conn.executed == []


def test_a_workspace_kind_drops_the_channel_it_was_handed():
    conn = Conn([guard()])
    memberguards.for_action(conn, "shush", USER_ID, channel_id=CHANNEL_ID)
    assert conn.executed[0][1] == (USER_ID, "shush", None)


def test_a_channel_kind_keeps_its_channel():
    conn = Conn([guard(kind="channel_ban", channel_id=CHANNEL_ID)])
    memberguards.for_action(conn, "channel_ban", USER_ID, channel_id=CHANNEL_ID)
    assert conn.executed[0][1] == (USER_ID, "channel_ban", CHANNEL_ID)


def test_a_guard_comes_back_as_something_readable():
    conn = Conn([guard(case_id=412)])
    guard_row = memberguards.for_action(conn, "shush", USER_ID)
    assert guard_row["id"] == 7
    assert guard_row["case_id"] == 412
    assert guard_row["reason"] == "being awful"


def test_nothing_standing_reads_as_unguarded():
    assert memberguards.reads(None) == memberguards.UNGUARDED
    assert memberguards.reads(None, 412) == memberguards.UNGUARDED


def test_a_guard_with_no_case_is_the_one_worth_adopting():
    guard_row = memberguards.row_to_guard(guard(case_id=None))
    assert memberguards.reads(guard_row, 412) == memberguards.ORPHANED
    assert memberguards.reads(guard_row) == memberguards.ORPHANED


def test_a_guard_on_this_case_is_already_here():
    guard_row = memberguards.row_to_guard(guard(case_id=412))
    assert memberguards.reads(guard_row, 412) == memberguards.HERE


def test_a_guard_on_another_case_is_elsewhere():
    guard_row = memberguards.row_to_guard(guard(case_id=318))
    assert memberguards.reads(guard_row, 412) == memberguards.ELSEWHERE


def test_a_cased_guard_read_without_a_case_is_not_claimed_as_ours():
    guard_row = memberguards.row_to_guard(guard(case_id=318))
    assert memberguards.reads(guard_row) == memberguards.ELSEWHERE


def test_only_a_guard_still_on_counts_as_standing():
    assert "state IN ('live', 'lifting')" in memberguards.ACTIVE_GUARD
    assert "state IN ('live', 'lifting')" in memberguards.FOR_MEMBER


def test_the_standing_lookup_matches_the_one_live_index():
    assert "coalesce(channel_id, '') = coalesce(%s, '')" in memberguards.ACTIVE_GUARD


def test_everything_on_a_member_comes_back_oldest_first():
    conn = Conn([guard(id=1), guard(id=2, kind="channel_ban", channel_id=CHANNEL_ID)])
    guards = memberguards.for_member(conn, USER_ID)
    assert [one["id"] for one in guards] == [1, 2]
    assert conn.executed[0][1] == (USER_ID,)
