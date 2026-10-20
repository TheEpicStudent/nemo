from bot.nemo import case_actions
from bot.nemo.views import action

CASE_ID = 412
USER_ID = "U1"
MOD = "UMOD"
HELPER = "UHELP"


class Conn:
    def __init__(self, row):
        self.row = row
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        return self.row

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


def submission(**over):
    row = {"type_key": "warning", "target_user_id": USER_ID, "reason": "kept at it after being asked to stop"}
    row.update(over)
    return row


def block(built, block_id):
    return next(one for one in built if one.get("block_id") == block_id)


def test_build_blocks_has_solution_resolvers_and_resolve_tick_with_lyla_labels():
    built = action.build_blocks(CASE_ID, submission())
    assert block(built, action.SOLUTION)["label"]["text"] == "How Was This Solved? (Text edition)"
    assert block(built, action.RESOLVERS)["label"]["text"] == "Who Resolved This? (Thank you btw <3)"
    assert block(built, action.RESOLVE)["label"]["text"] == "Resolve Case?"
    assert all(block(built, one)["optional"] for one in (action.SOLUTION, action.RESOLVERS, action.RESOLVE))


def test_build_blocks_leaves_resolve_tick_unticked_by_default():
    built = action.build_blocks(CASE_ID, submission())
    assert "initial_options" not in block(built, action.RESOLVE)["element"]
    assert "initial_users" not in block(built, action.RESOLVERS)["element"]


def test_build_blocks_keeps_entered_solution_resolvers_and_tick():
    built = action.build_blocks(
        CASE_ID, submission(solution="removed the post", resolved_by=[MOD, HELPER], resolve_case=True)
    )
    assert block(built, action.SOLUTION)["element"]["initial_value"] == "removed the post"
    assert block(built, action.RESOLVERS)["element"]["initial_users"] == [MOD, HELPER]
    assert block(built, action.RESOLVE)["element"]["initial_options"] == [action.RESOLVE_OPTION]


def test_submitted_values_reads_solution_resolvers_and_tick():
    values = action.submitted_values({"values": {
        action.SOLUTION: {action.SOLUTION: {"value": "  removed the post  "}},
        action.RESOLVERS: {action.RESOLVERS: {"selected_users": [MOD, HELPER]}},
        action.RESOLVE: {action.RESOLVE: {"selected_options": [{"value": action.RESOLVE_CASE}]}},
    }})
    assert values["solution"] == "removed the post"
    assert values["resolved_by"] == [MOD, HELPER]
    assert values["resolve_case"] is True


def test_submitted_values_defaults_when_left_empty():
    values = action.submitted_values({"values": {}})
    assert values["solution"] == ""
    assert values["resolved_by"] == []
    assert values["resolve_case"] is False


def test_resolvers_default_to_the_person_logging():
    assert action.resolvers(submission(), MOD) == [MOD]
    assert action.resolvers(submission(resolved_by=[HELPER]), MOD) == [HELPER]


def test_log_blocks_names_resolvers_other_than_the_logger():
    built = action.log_blocks(submission(resolved_by=[MOD, HELPER]), MOD)
    assert built[1]["elements"][0]["text"] == (
        f"Against <@{USER_ID}>, logged by <@{MOD}>, resolved by <@{MOD}>, <@{HELPER}>"
    )


def test_log_blocks_leaves_out_resolvers_when_only_the_logger():
    built = action.log_blocks(submission(resolved_by=[MOD]), MOD)
    assert built[1]["elements"][0]["text"] == f"Against <@{USER_ID}>, logged by <@{MOD}>"


def test_log_blocks_shows_solution():
    built = action.log_blocks(submission(solution="removed the post"), MOD)
    assert built[-1]["elements"][0]["text"] == "*How Was This Solved?* removed the post"


def test_log_action_stores_solution_and_resolvers(monkeypatch):
    monkeypatch.setattr(case_actions.audit, "record", lambda *args, **kwargs: None)
    conn = Conn((55, None, "spam"))
    case_actions.log_action(conn, CASE_ID, submission(solution="removed the post", resolved_by=[HELPER]), MOD)
    args = conn.args_for("INSERT INTO fd.actions")[0]
    assert "removed the post" in args
    assert [HELPER] in args


def test_log_action_resolvers_default_to_the_logger(monkeypatch):
    monkeypatch.setattr(case_actions.audit, "record", lambda *args, **kwargs: None)
    conn = Conn((55, None, "spam"))
    case_actions.log_action(conn, CASE_ID, submission(), MOD)
    args = conn.args_for("INSERT INTO fd.actions")[0]
    assert [MOD] in args
    assert args[9] is None
