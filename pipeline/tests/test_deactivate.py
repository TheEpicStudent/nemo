import pathlib

import pytest

from bot.nemo import memberguards
from bot.nemo.enforcement import deactivate

USER_ID = "U1"


class Conn:
    def __init__(self, lift_returns_row=True, action_returns_row=True):
        self.lift_returns_row = lift_returns_row
        self.action_returns_row = action_returns_row
        self.statements = []

    def execute(self, sql, args=None):
        self.statements.append((sql, args))
        return self

    def fetchone(self):
        sql, _ = self.statements[-1]
        if "JOIN fd.actions" in sql:
            return (7, memberguards.DEACTIVATION) if self.action_returns_row else None
        if "SET state = 'lifted'" in sql:
            return (7,) if self.lift_returns_row else None
        return (7,)

    def args_for(self, mark):
        return [args for sql, args in self.statements if mark in sql]

    def executed(self, mark):
        return any(mark in sql for sql, _ in self.statements)


class Slack:
    pass


def guard(**over):
    row = {"id": 7, "kind": "deactivation", "subject_id": USER_ID, "channel_id": None,
           "reason": "raiding", "expires_at": None}
    row.update(over)
    return row


@pytest.fixture
def slack_outcome(monkeypatch):
    def set_outcome(outcome):
        monkeypatch.setattr(deactivate.privileged, "deactivate", lambda user_id, conn=None: outcome)
        monkeypatch.setattr(deactivate.privileged, "reactivate", lambda user_id, conn=None: outcome)
    return set_outcome


def test_taking_one_up_holds_the_guard_and_writes_down_what_slack_did(slack_outcome):
    slack_outcome("deactivated")
    conn = Conn()
    assert deactivate.take_up(Slack(), conn, guard())

    assert conn.executed("enforcement_status = 'held'")
    row = conn.args_for("INSERT INTO fd.member_guard_events")[0]
    assert row[3] == "deactivated"
    assert row[6] == "deactivated"


def test_an_account_slack_would_not_take_down_drops_the_guard(slack_outcome):
    slack_outcome("failed: user_not_found")
    conn = Conn()
    assert not deactivate.take_up(Slack(), conn, guard())

    assert conn.executed("enforcement_status = 'failed'")
    assert not conn.executed("enforcement_status = 'held'")
    assert conn.args_for("INSERT INTO fd.member_guard_events")[0][3] == "failed"


@pytest.mark.parametrize("how", ["off", "would"])
def test_a_run_that_is_not_armed_still_reads_as_carried(slack_outcome, how):
    slack_outcome(how)
    conn = Conn()
    assert deactivate.take_up(Slack(), conn, guard())
    assert conn.executed("enforcement_status = 'held'")


def test_lifting_puts_them_back_before_the_guard_reads_as_lifted(slack_outcome):
    slack_outcome("reactivated")
    conn = Conn()
    assert deactivate.lift(Slack(), conn, guard())

    assert conn.executed("state = 'lifted'")
    assert conn.args_for("INSERT INTO fd.member_guard_events")[0][3] == "reactivated"


def test_a_lift_slack_refuses_leaves_the_guard_lifting(slack_outcome):
    slack_outcome("failed: rate limited")
    conn = Conn()
    assert not deactivate.lift(Slack(), conn, guard())

    assert not conn.executed("state = 'lifted'")
    assert conn.args_for("INSERT INTO fd.member_guard_events")[0][3] == "failed"


def test_a_lift_that_was_already_finished_says_so_once(slack_outcome):
    slack_outcome("reactivated")
    conn = Conn(lift_returns_row=False)
    assert deactivate.lift(Slack(), conn, guard())
    assert conn.args_for("INSERT INTO fd.member_guard_events") == []


def test_reversing_the_last_live_action_lifts_what_it_held():
    conn = Conn()
    assert memberguards.lift_for_action(conn, 3, "UME", "the action was reversed: appeal") == 7

    sql, args = conn.statements[0]
    assert "o.reversed_at IS NULL" in sql, "a guard another live action wants must stay"
    assert args == (3,)
    assert conn.executed("state = 'lifting'"), "a deactivation waits for slack before it is lifted"


def test_reversing_an_action_that_held_nothing_lifts_nothing():
    conn = Conn(action_returns_row=False)
    assert memberguards.lift_for_action(conn, 3, "UME", "why") is None
    assert not conn.executed("UPDATE fd.member_guards")


def test_only_a_deactivation_waits_for_slack_before_it_reads_as_lifted():
    assert memberguards.undone_in_slack(memberguards.DEACTIVATION)
    assert not memberguards.undone_in_slack(memberguards.SHUSH)
    assert not memberguards.undone_in_slack(memberguards.CHANNEL_BAN)


def test_the_lift_the_web_asks_for_reaches_the_bot_without_waiting_for_a_sweep():
    from bot.nemo import loop

    loop_source = pathlib.Path(loop.__file__).read_text()
    assert "still_lifting" in loop_source, "the listener must drain what is lifting"
    assert "lambda: flush_pending(case_channel.client)" in loop_source
    assert "wake_member_guards()" in loop_source


def test_the_kind_and_the_events_the_database_will_take():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0140_deactivation_guards.sql").read_text()
    assert "'shush', 'channel_ban', 'deactivation'" in sql
    assert "'deactivated', 'reactivated'" in sql
