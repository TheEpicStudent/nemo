import datetime as dt

from bot.nemo import memberguards
from bot.nemo.views import action

USER_ID = "U1"
MOD = "UMOD"
CHANNEL_ID = "C1"
EXPIRES_AT = dt.datetime(2026, 3, 10, 12, tzinfo=dt.UTC)


class Conn:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else {}
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        for mark, row in self.rows.items():
            if mark in self.executed[-1][0]:
                return row
        return None

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


def guard(**over):
    row = {
        "id": 7, "kind": "shush", "subject_id": USER_ID, "channel_id": None,
        "state": "live", "enforcement_status": "held", "enforced_by": "nemo", "case_id": None,
        "opened_by": MOD, "opened_at": None, "reason": "being awful", "expires_at": EXPIRES_AT,
    }
    row.update(over)
    return row


def standing(guard_row, relation, case_id=412, enforceable=True):
    return {"enforceable": enforceable, "guard": guard_row, "relation": relation, "case_id": case_id}


FUTURE = (dt.date.today() + dt.timedelta(days=30)).isoformat()


def submission(**over):
    row = {"type_key": "shush", "target_user_id": USER_ID, "reason": "being awful",
           "expires_on": FUTURE}
    row.update(over)
    return row


def options(submitted, standing_):
    return [value for value, _text in action.enforcement_options(submitted, standing_)]


def test_enforcement_options_record_only_kind_returns_empty():
    assert options(submission(type_key="warning"), standing(None, action.NO_GUARD,
                                                      enforceable=False)) == []


def test_enforcement_options_no_guard_returns_empty():
    assert options(submission(), standing(None, action.NO_GUARD)) == []


def test_enforcement_options_guard_without_case_offers_attach_then_log_only():
    assert options(submission(), standing(guard(), action.NO_CASE)) == [action.ATTACH, action.LOG_ONLY]


def test_enforcement_blocks_other_case_guard_defaults_to_log_only():
    built = action.enforcement_blocks(submission(), standing(guard(case_id=318), action.OTHER_CASE))
    submitted_values = built[0]["element"]["initial_option"]["value"]
    assert submitted_values == action.LOG_ONLY
    assert options(submission(), standing(guard(case_id=318), action.OTHER_CASE)) == [
        action.EXTEND, action.LOG_ONLY]


def test_enforcement_blocks_guard_without_case_defaults_to_attach():
    built = action.enforcement_blocks(submission(), standing(guard(), action.NO_CASE))
    assert built[0]["element"]["initial_option"]["value"] == action.ATTACH


def test_enforcement_options_indefinite_kind_omits_extend():
    guard_row = guard(kind="indef_ban", expires_at=None)
    assert options(submission(type_key="indef_ban"), standing(guard_row, action.OTHER_CASE)) == []


def test_enforcement_blocks_keeps_submitted_enforcement():
    built = action.enforcement_blocks(submission(enforcement=action.LOG_ONLY),
                                      standing(guard(), action.NO_CASE))
    assert built[0]["element"]["initial_option"]["value"] == action.LOG_ONLY


def test_build_blocks_enforcement_follows_until():
    built = action.build_blocks(412, submission(), standing(guard(case_id=318), action.OTHER_CASE))
    block_ids = [one.get("block_id") for one in built]
    assert block_ids.index(action.UNTIL) < block_ids.index(action.ENFORCEMENT)


def test_requires_refresh_no_guard_returns_false():
    visible_blocks = {action.TARGET, action.KIND, action.UNTIL, action.REASON}
    assert not action.requires_refresh(submission(), visible_blocks, standing(None, action.NO_GUARD))


def test_requires_refresh_enforcement_block_missing_returns_true():
    visible_blocks = {action.TARGET, action.KIND, action.UNTIL, action.REASON, action.GUARD_STATUS}
    orphaned_standing = standing(guard(), action.NO_CASE)
    assert action.requires_refresh(submission(), visible_blocks, orphaned_standing)
    assert not action.requires_refresh(submission(), visible_blocks | {action.ENFORCEMENT}, orphaned_standing)


def test_validation_errors_extend_without_date_flags_until():
    errors = action.validation_errors(submission(enforcement=action.EXTEND, expires_on=None))
    assert action.UNTIL in errors


def test_apply_enforcement_open_guard_inserts_pending_guard():
    conn = Conn({"INSERT INTO fd.member_guards": (9,), "UPDATE fd.actions": (1,)})
    guard_id = memberguards.apply_enforcement(conn, 1, submission(enforcement=action.OPEN_GUARD),
                                              standing(None, action.NO_GUARD), MOD)
    assert guard_id == 9
    insert_args = conn.args_for("INSERT INTO fd.member_guards")[0]
    assert insert_args[0] == "shush"
    assert insert_args[3] == 412
    assert insert_args[7:9] == ("nemo", "pending")
    assert conn.args_for("UPDATE fd.actions")[0] == (9, 1)


def test_apply_enforcement_no_guard_defaults_to_pending_guard():
    conn = Conn({"INSERT INTO fd.member_guards": (9,), "UPDATE fd.actions": (1,)})
    memberguards.apply_enforcement(conn, 1, submission(), standing(None, action.NO_GUARD), MOD)
    assert conn.args_for("INSERT INTO fd.member_guards")[0][7:9] == ("nemo", "pending")


def test_apply_enforcement_shush_open_guard_has_no_channel():
    conn = Conn({"INSERT INTO fd.member_guards": (9,), "UPDATE fd.actions": (1,)})
    memberguards.apply_enforcement(conn, 1, submission(enforcement=action.OPEN_GUARD, channel_id=CHANNEL_ID),
                                   standing(None, action.NO_GUARD), MOD)
    assert conn.args_for("INSERT INTO fd.member_guards")[0][2] is None


def test_apply_enforcement_channel_ban_keeps_channel_id():
    conn = Conn({"INSERT INTO fd.member_guards": (9,), "UPDATE fd.actions": (1,)})
    memberguards.apply_enforcement(conn, 1,
                                   submission(type_key="channel_ban", enforcement=action.OPEN_GUARD, channel_id=CHANNEL_ID),
                                   standing(None, action.NO_GUARD), MOD)
    assert conn.args_for("INSERT INTO fd.member_guards")[0][2] == CHANNEL_ID


def test_apply_enforcement_attach_sets_case_and_links_action():
    conn = Conn({"UPDATE fd.member_guards SET case_id": (7,), "UPDATE fd.actions": (1,)})
    guard_id = memberguards.apply_enforcement(conn, 1, submission(enforcement=action.ATTACH),
                                              standing(guard(), action.NO_CASE), MOD)
    assert guard_id == 7
    assert conn.args_for("UPDATE fd.member_guards SET case_id")[0] == (412, 7)
    assert conn.args_for("UPDATE fd.actions")[0] == (7, 1)


def test_apply_enforcement_log_only_without_case_leaves_guard_and_action_unlinked():
    conn = Conn({"UPDATE fd.actions": (1,)})
    guard_id = memberguards.apply_enforcement(conn, 1, submission(enforcement=action.LOG_ONLY),
                                              standing(guard(), action.NO_CASE), MOD)
    assert guard_id is None
    assert conn.args_for("UPDATE fd.member_guards SET case_id") == []
    assert conn.args_for("UPDATE fd.actions") == []


def test_apply_enforcement_extend_updates_expires_at():
    conn = Conn({"UPDATE fd.member_guards SET expires_at": (7,), "UPDATE fd.actions": (1,)})
    memberguards.apply_enforcement(conn, 1, submission(enforcement=action.EXTEND, expires_on="2026-04-01"),
                                   standing(guard(case_id=318), action.OTHER_CASE), MOD)
    assert conn.args_for("UPDATE fd.member_guards SET expires_at")[0] == \
        (dt.datetime(2026, 4, 1, 23, 59, 59, tzinfo=dt.UTC), 7)


def test_apply_enforcement_log_only_other_case_returns_none():
    conn = Conn({"UPDATE fd.actions": (1,)})
    guard_id = memberguards.apply_enforcement(conn, 1, submission(enforcement=action.LOG_ONLY),
                                              standing(guard(case_id=318), action.OTHER_CASE), MOD)
    assert guard_id is None
    assert conn.args_for("UPDATE fd.actions") == []


def test_apply_enforcement_log_only_this_case_links_action_only():
    conn = Conn({"UPDATE fd.actions": (1,)})
    guard_id = memberguards.apply_enforcement(conn, 1, submission(enforcement=action.LOG_ONLY),
                                              standing(guard(case_id=412), action.THIS_CASE), MOD)
    assert guard_id == 7
    assert conn.args_for("UPDATE fd.member_guards SET case_id") == []
    assert conn.args_for("UPDATE fd.actions")[0] == (7, 1)


def test_apply_enforcement_record_only_kind_executes_nothing():
    conn = Conn()
    assert memberguards.apply_enforcement(conn, 1, submission(type_key="warning"),
                                          standing(None, action.NO_GUARD, enforceable=False), MOD) is None
    assert conn.executed == []


def test_apply_enforcement_open_guard_conflict_leaves_action_unlinked():
    conn = Conn({"UPDATE fd.actions": (1,)})
    guard_id = memberguards.apply_enforcement(conn, 1, submission(enforcement=action.OPEN_GUARD),
                                              standing(None, action.NO_GUARD), MOD)
    assert guard_id is None
    assert conn.args_for("UPDATE fd.actions") == []


def test_apply_enforcement_attach_conflict_leaves_action_unlinked():
    conn = Conn({"UPDATE fd.actions": (1,)})
    guard_id = memberguards.apply_enforcement(conn, 1, submission(enforcement=action.ATTACH),
                                              standing(guard(), action.NO_CASE), MOD)
    assert guard_id is None
    assert conn.args_for("UPDATE fd.actions") == []


def verbs(conn):
    return [args[4] for args in conn.args_for("INSERT INTO fd.audit")]


def test_apply_enforcement_open_guard_records_opened_audit():
    conn = Conn({"INSERT INTO fd.member_guards": (9,), "UPDATE fd.actions": (1,)})
    memberguards.apply_enforcement(conn, 1, submission(enforcement=action.OPEN_GUARD),
                                   standing(None, action.NO_GUARD), MOD)
    recorded = conn.args_for("INSERT INTO fd.audit")[0]
    assert recorded[2:5] == ("member_guard", 9, "opened")


def test_apply_enforcement_attach_and_extend_record_audit_verbs():
    conn = Conn({"UPDATE fd.member_guards SET case_id": (7,), "UPDATE fd.actions": (1,)})
    memberguards.apply_enforcement(conn, 1, submission(enforcement=action.ATTACH),
                                   standing(guard(), action.NO_CASE), MOD)
    assert verbs(conn) == ["attached"]

    conn = Conn({"UPDATE fd.member_guards SET expires_at": (7,), "UPDATE fd.actions": (1,)})
    memberguards.apply_enforcement(conn, 1, submission(enforcement=action.EXTEND),
                                   standing(guard(case_id=318), action.OTHER_CASE), MOD)
    assert verbs(conn) == ["extended"]


def test_apply_enforcement_log_only_records_no_audit():
    conn = Conn({"UPDATE fd.actions": (1,)})
    memberguards.apply_enforcement(conn, 1, submission(enforcement=action.LOG_ONLY),
                                   standing(guard(case_id=412), action.THIS_CASE), MOD)
    assert verbs(conn) == []


def test_case_act_capability_declares_member_guard_events():
    import yaml
    from lib.paths import CAPABILITIES_FILE

    config = yaml.safe_load(CAPABILITIES_FILE.read_text())
    declared = set(config["capabilities"]["case.act"]["events"])
    assert {"member_guard/opened", "member_guard/attached",
            "member_guard/extended"} <= declared
