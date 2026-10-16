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


def guard(**overrides):
    row = {
        "id": 7, "kind": "shush", "subject_id": USER_ID, "channel_id": None,
        "state": "live", "enforcement_status": "held", "enforced_by": "nemo", "case_id": None,
        "opened_by": "UMOD", "opened_at": None, "reason": "being awful",
        "expires_at": None,
    }
    row.update(overrides)
    return tuple(row[field] for field in memberguards.FIELDS)


def test_action_guard_kind_scope_and_mode_for_enforceable_types():
    assert action.guard_kind("shush") == "shush"
    assert action.guard_scope("shush") == "workspace"
    assert action.guard_mode("shush") == "reactive"
    assert action.guard_kind("channel_ban") == "channel_ban"
    assert action.guard_scope("channel_ban") == "channel"


@pytest.mark.parametrize("type_key", ["warning", "locked_thread", "dm"])
def test_guard_kind_without_enforce_block_is_not_enforceable(type_key):
    assert action.guard_kind(type_key) is None
    assert action.enforce(type_key) == {}
    assert not memberguards.enforceable(type_key)


@pytest.mark.parametrize("type_key", ["temp_ban", "indef_ban", "perma_ban"])
def test_ban_types_map_to_deactivation_guard_kind(type_key):
    assert action.guard_kind(type_key) == memberguards.DEACTIVATION
    assert action.guard_scope(type_key) == "account"
    assert action.guard_mode(type_key) == "applied"
    assert memberguards.enforceable(type_key)


def test_for_action_deactivation_ignores_channel_id():
    conn = Conn([guard(kind=memberguards.DEACTIVATION)])
    memberguards.for_action(conn, "perma_ban", USER_ID, channel_id="C9")
    assert conn.executed[0][1] == (USER_ID, memberguards.DEACTIVATION, None)


def test_enforceable_unknown_type_returns_false():
    assert action.guard_kind("nonsense") is None
    assert not memberguards.enforceable("nonsense")


def test_for_action_record_only_type_returns_none_without_query():
    conn = Conn([guard()])
    assert memberguards.for_action(conn, "warning", USER_ID) is None
    assert conn.executed == []


def test_for_action_workspace_kind_ignores_channel_id():
    conn = Conn([guard()])
    memberguards.for_action(conn, "shush", USER_ID, channel_id=CHANNEL_ID)
    assert conn.executed[0][1] == (USER_ID, "shush", None)


def test_for_action_channel_kind_passes_channel_id():
    conn = Conn([guard(kind="channel_ban", channel_id=CHANNEL_ID)])
    memberguards.for_action(conn, "channel_ban", USER_ID, channel_id=CHANNEL_ID)
    assert conn.executed[0][1] == (USER_ID, "channel_ban", CHANNEL_ID)


def test_for_action_returns_guard_dict():
    conn = Conn([guard(case_id=412)])
    guard_row = memberguards.for_action(conn, "shush", USER_ID)
    assert guard_row["id"] == 7
    assert guard_row["case_id"] == 412
    assert guard_row["reason"] == "being awful"


def test_guard_relation_without_guard_returns_no_guard():
    assert memberguards.guard_relation(None) == memberguards.NO_GUARD
    assert memberguards.guard_relation(None, 412) == memberguards.NO_GUARD


def test_guard_relation_guard_without_case_returns_no_case():
    guard_row = memberguards.row_to_guard(guard(case_id=None))
    assert memberguards.guard_relation(guard_row, 412) == memberguards.NO_CASE
    assert memberguards.guard_relation(guard_row) == memberguards.NO_CASE


def test_guard_relation_guard_on_same_case_returns_this_case():
    guard_row = memberguards.row_to_guard(guard(case_id=412))
    assert memberguards.guard_relation(guard_row, 412) == memberguards.THIS_CASE


def test_guard_relation_guard_on_other_case_returns_other_case():
    guard_row = memberguards.row_to_guard(guard(case_id=318))
    assert memberguards.guard_relation(guard_row, 412) == memberguards.OTHER_CASE


def test_guard_relation_cased_guard_without_case_argument_returns_other_case():
    guard_row = memberguards.row_to_guard(guard(case_id=318))
    assert memberguards.guard_relation(guard_row) == memberguards.OTHER_CASE


def test_active_guard_sql_filters_live_and_lifting_states():
    assert "state IN ('live', 'lifting')" in memberguards.ACTIVE_GUARD
    assert "state IN ('live', 'lifting')" in memberguards.FOR_MEMBER


def test_active_guard_sql_matches_coalesced_channel_id_index():
    assert "coalesce(channel_id, '') = coalesce(%s, '')" in memberguards.ACTIVE_GUARD


def test_for_member_returns_every_guard_for_member():
    conn = Conn([guard(id=1), guard(id=2, kind="channel_ban", channel_id=CHANNEL_ID)])
    guards = memberguards.for_member(conn, USER_ID)
    assert [one["id"] for one in guards] == [1, 2]
    assert conn.executed[0][1] == (USER_ID,)
