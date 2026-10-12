import datetime as dt

import pytest

from bot.nemo import memberguards
from bot.nemo.enforcement import channel_ban, shush, sweep

USER_ID = "U1"
CHANNEL_ID = "C1"
LOG_CHANNEL_ID = "CHOUSE"
EXPIRES_AT = dt.datetime(2026, 3, 10, 12, tzinfo=dt.UTC)


class Conn:
    def __init__(self, lift_returns_row=True, settings=None):
        self.lift_returns_row = lift_returns_row
        self.settings = settings or {}
        self.statements = []

    def execute(self, sql, args=None):
        self.statements.append((sql, args))
        return self

    def fetchone(self):
        sql, args = self.statements[-1]
        if "SET state = 'lifted'" in sql:
            return (7,) if self.lift_returns_row else None
        if "FROM fd.app_settings" in sql:
            value = self.settings.get(args[0])
            return (value,) if value is not None else None
        return (1,)

    def fetchall(self):
        return []

    def args_for(self, mark):
        return [args for sql, args in self.statements if mark in sql]

    def executed(self, mark):
        return any(mark in sql for sql, _ in self.statements)

    def verbs(self):
        return [args[3] for args in self.args_for("INSERT INTO fd.member_guard_events")]


class Slack:
    def __init__(self):
        self.posted = []

    def chat_postMessage(self, **kwargs):
        self.posted.append(kwargs)
        return {"ts": "9.9"}


def guard(**over):
    row = {"id": 7, "kind": "shush", "subject_id": USER_ID, "channel_id": None,
           "reason": "being awful", "expires_at": EXPIRES_AT, "case_id": 412}
    row.update(over)
    return row


def test_a_lift_by_hand_is_swept_only_until_it_has_been_said():
    assert "state = 'lifted'" in memberguards.LIFTED_NOT_NOTIFIED
    assert "enforced_by = 'nemo'" in memberguards.LIFTED_NOT_NOTIFIED
    assert "e.verb = 'released'" in memberguards.LIFTED_NOT_NOTIFIED


def test_somebody_whose_shush_was_lifted_in_the_dashboard_is_notified(monkeypatch):
    client = Slack()
    recorded = []
    monkeypatch.setattr(sweep.memberguards, "lifted_not_notified",
                        lambda _conn, _within: [guard()])
    monkeypatch.setattr(sweep.memberguards, "record_enforcement",
                        lambda *args, **over: recorded.append(args[4]))
    monkeypatch.setattr(sweep, "session", lambda: FakeSession())
    monkeypatch.setattr(sweep, "notifies_member", lambda _conn: True)

    assert sweep.sweep_lifted(client) == 1
    assert recorded == [memberguards.RELEASED, memberguards.NOTIFIED]
    assert "can post again" in client.posted[0]["text"]


class FakeSession:
    def __enter__(self):
        return Conn()

    def __exit__(self, *_):
        return False


def test_only_a_date_already_passed_is_swept():
    assert "expires_at <= now()" in memberguards.LAPSED
    assert "state = 'live'" in memberguards.LAPSED
    assert "expires_at IS NOT NULL" in memberguards.LAPSED, "endless ones never lapse"


def test_lifting_one_that_ran_out_says_why_and_notifies_them():
    conn, client = Conn(), Slack()
    assert sweep.lapse(client, conn, guard())

    lift_args = conn.args_for("SET state = 'lifted'")[0]
    assert lift_args[0] == "nemo"
    assert lift_args[1] == sweep.LAPSED_BECAUSE
    assert "released" in conn.verbs()
    assert "Your shush has ended" in client.posted[0]["text"]


def test_a_ban_that_ran_out_says_they_can_come_back():
    conn, client = Conn(), Slack()
    sweep.lapse(client, conn, guard(kind="channel_ban", channel_id=CHANNEL_ID))
    assert f"ban from <#{CHANNEL_ID}> has ended" in client.posted[0]["text"]


def test_one_somebody_lifted_first_is_left_alone():
    conn, client = Conn(lift_returns_row=False), Slack()
    assert not sweep.lapse(client, conn, guard())
    assert conn.verbs() == []
    assert client.posted == []


def test_a_kind_with_no_enforcement_still_lifts():
    conn, client = Conn(), Slack()
    assert sweep.lapse(client, conn, guard(kind="deactivate"))
    assert "released" in conn.verbs()
    assert client.posted == []


def test_a_dropped_carry_waits_longer_each_time_it_fails():
    assert "least(attempts, %s) * interval '1 minute'" in memberguards.DROPPED_AWHILE
    assert memberguards.BACKOFF_CAP == 30


def test_only_what_nemo_carries_is_retried():
    assert "enforced_by = 'nemo'" in memberguards.DROPPED_AWHILE
    assert "enforcement_status = 'failed'" in memberguards.DROPPED_AWHILE


def test_retrying_goes_back_through_the_enforcement(monkeypatch):
    processed_ids = []
    monkeypatch.setattr(shush, "take_up", lambda c, conn, guard_row: processed_ids.append(guard_row["id"]))
    monkeypatch.setattr(memberguards, "dropped_awhile", lambda conn: [guard()])
    monkeypatch.setattr(sweep, "session", _session(Conn()))

    assert sweep.sweep_dropped(Slack()) == 1
    assert processed_ids == [7]


def _session(conn):
    class FakeSession:
        def __enter__(self):
            return conn

        def __exit__(self, *failure):
            return False

    return lambda: FakeSession()


def test_the_nudge_names_who_what_when_and_the_case():
    line = sweep.line_about(guard())
    assert "<@U1>" in line
    assert "shush" in line
    assert "until 10 Mar" in line
    assert "(case 412)" in line


def test_a_ban_in_the_nudge_names_its_channel():
    line = sweep.line_about(guard(kind="channel_ban", channel_id=CHANNEL_ID))
    assert f"channel ban in <#{CHANNEL_ID}>" in line


def test_one_on_no_case_is_called_out_in_the_nudge():
    assert "on no case" in sweep.line_about(guard(case_id=None))


def test_the_nudge_goes_out_once_and_is_written_down(monkeypatch):
    conn = Conn()
    monkeypatch.setattr(memberguards, "ending_not_notified", lambda c, within: [guard()])
    monkeypatch.setattr(sweep.channel, "internal_log_channel", lambda c: LOG_CHANNEL_ID)
    monkeypatch.setattr(sweep, "session", _session(conn))
    client = Slack()

    assert sweep.sweep_ending(client) == 1
    assert client.posted[0]["channel"] == LOG_CHANNEL_ID
    assert "Ending soon" in client.posted[0]["text"]
    recorded = conn.args_for("INSERT INTO fd.member_guard_events")[0]
    assert recorded[3] == memberguards.NOTIFIED
    assert recorded[6] == memberguards.ENDING


def test_nothing_ending_says_nothing(monkeypatch):
    monkeypatch.setattr(memberguards, "ending_not_notified", lambda c, within: [])
    monkeypatch.setattr(sweep.channel, "internal_log_channel", lambda c: LOG_CHANNEL_ID)
    monkeypatch.setattr(sweep, "session", _session(Conn()))
    client = Slack()

    assert sweep.sweep_ending(client) == 0
    assert client.posted == []


def test_the_same_guard_is_not_nudged_twice_in_a_day():
    assert "interval '20 hours'" in memberguards.ENDING_NOT_NOTIFIED
    assert "verb = 'notified'" in memberguards.ENDING_NOT_NOTIFIED


@pytest.mark.parametrize("enforcement", [shush, channel_ban])
def test_every_enforcement_can_be_let_go(enforcement):
    conn, client = Conn(), Slack()
    enforcement.lift(client, conn, guard(kind=enforcement.KIND, channel_id=CHANNEL_ID))
    assert client.posted, f"{enforcement.KIND} says nothing when it ends"


def test_the_ending_horizon_falls_back_when_it_is_not_set():
    assert sweep.expiring_soon(Conn()) == "36 hours"


def test_the_ending_horizon_is_read_from_the_setting():
    assert sweep.expiring_soon(Conn(settings={"nemo.sweep_soon_hours": "12"})) == "12 hours"


def test_an_horizon_outside_the_range_falls_back():
    assert sweep.expiring_soon(Conn(settings={"nemo.sweep_soon_hours": "0"})) == "36 hours"
    assert sweep.expiring_soon(Conn(settings={"nemo.sweep_soon_hours": "9999"})) == "36 hours"
    assert sweep.expiring_soon(Conn(settings={"nemo.sweep_soon_hours": "sideways"})) == "36 hours"


def test_the_member_is_notified_unless_it_is_turned_off():
    assert sweep.notifies_member(Conn()) is True
    assert sweep.notifies_member(Conn(settings={"nemo.sweep_tells_member": "on"})) is True
    assert sweep.notifies_member(Conn(settings={"nemo.sweep_tells_member": "off"})) is False


def test_a_lapse_says_nothing_when_notifying_is_off():
    conn = Conn(settings={"nemo.sweep_tells_member": "off"})
    client = Slack()
    sweep.lapse(client, conn, guard())

    assert client.posted == []
    assert "released" in conn.verbs()

