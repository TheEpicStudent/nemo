import contextlib

import pytest

from bot.nemo import thread_commands as commands

CHANNEL_ID = "C_FIRE"
THREAD = "100.000"


class Conn:
    def __init__(self, assignees=()):
        self.assignees = list(assignees)
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return [(one,) for one in self.assignees]


class Slack:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda **kwargs: self.calls.append((name, kwargs)) or {"ok": True}

    def calls_to(self, name):
        return [kwargs for method, kwargs in self.calls if method == name]


@pytest.fixture
def harness(monkeypatch):
    recorded = {"claimed": [], "assigned": [], "removed": [], "noted": [], "member": [],
                "deleted": []}
    conn = Conn()

    @contextlib.contextmanager
    def one_session():
        yield conn

    monkeypatch.setattr(commands, "session", one_session)
    monkeypatch.setattr(commands.access, "may", lambda conn, user_id, capability, case=None: (True, None))
    monkeypatch.setattr(commands.case_actions, "claimed",
                        lambda conn, case_id, user_id: recorded["claimed"].append(user_id))
    monkeypatch.setattr(commands.case_actions, "assign_people",
                        lambda conn, case_id, users, by: recorded["assigned"].append(users))
    monkeypatch.setattr(commands.case_actions, "remove_assignee",
                        lambda conn, case_id, user, by: recorded["removed"].append(user))
    monkeypatch.setattr(commands.case_actions, "add_note",
                        lambda conn, case_id, body, by: recorded["noted"].append(body))
    monkeypatch.setattr(commands.case_actions, "member_note",
                        lambda conn, user, body, by: recorded["member"].append((user, body)))
    monkeypatch.setattr(commands.privileged, "delete_message",
                        lambda channel_id, ts, max_retries=2: recorded["deleted"].append(ts))
    monkeypatch.setattr(commands.channel, "case_url", lambda case_id: None)
    recorded["conn"] = conn
    return recorded


def test_commands_are_read_from_the_first_word():
    assert commands.parse_command("!claim") == ("!claim", "")
    assert commands.parse_command("!Assign <@UA>  <@UB>") == ("!assign", "<@UA>  <@UB>")
    assert commands.parse_command("  ?Resolve ") == ("resolve", "")
    assert commands.parse_command("!resolve") == ("resolve", "")
    assert commands.parse_command("?we are looking at it") == (None, None)
    assert commands.parse_command("!whatever") == (None, None)


def test_claiming_assigns_you(harness):
    outcome = commands.run("!claim", "", 39, "UME")
    assert harness["claimed"] == ["UME"]
    assert outcome["say"] == ["<@UME> claimed case 39"]


def test_claiming_a_case_you_have_is_refused(harness):
    harness["conn"].assignees = ["UME", "UOTHER"]
    outcome = commands.run("!claim", "", 39, "UME")
    assert outcome["refused"] == "You are already assigned to case 39"
    assert harness["claimed"] == []


def test_claiming_beside_somebody_else_works(harness):
    harness["conn"].assignees = ["UOTHER"]
    assert commands.run("!claim", "", 39, "UME")["refused"] is None


def test_assign_adds_only_who_is_not_on_it(harness):
    harness["conn"].assignees = ["UA"]
    outcome = commands.run("!assign", "<@UA> <@UB|bob>", 39, "UME")
    assert harness["assigned"] == [["UB"]]
    assert outcome["say"] == ["<@UME> assigned case 39 to <@UB>"]


def test_assign_with_nobody_new_or_nobody_named_is_refused(harness):
    harness["conn"].assignees = ["UA"]
    assert commands.run("!assign", "<@UA>", 39, "UME")["refused"] == (
        "<@UA> is already assigned to case 39")
    assert commands.run("!assign", "", 39, "UME")["refused"] == "Usage: `!assign @user`"


def test_unassign_takes_people_off(harness):
    harness["conn"].assignees = ["UA", "UME"]
    outcome = commands.run("!unassign", "<@UME>", 39, "UME")
    assert harness["removed"] == ["UME"]
    assert outcome["say"] == ["<@UME> unassigned themselves from case 39"]
    assert commands.run("!unassign", "<@UZ>", 39, "UME")["refused"] == (
        "<@UZ> is not assigned to case 39")


def test_a_note_lands_on_the_case_or_the_member(harness):
    case = commands.run("!note", "spoke to them", 39, "UME")
    member = commands.run("!note", "<@UA> keeps doing this", 39, "UME")
    assert harness["noted"] == ["spoke to them"]
    assert harness["member"] == [("UA", "keeps doing this")]
    assert case == member == {"say": [], "react": "white_check_mark", "retain": True,
                              "refused": None}
    assert commands.run("!note", "<@UA>", 39, "UME")["refused"].startswith("Usage")


def test_each_command_asks_for_its_own_permission():
    assert commands.needed("!note", "<@UA> text") == "member.note"
    assert commands.needed("!note", "text") == "case.note"
    assert commands.needed("!claim", "") == "case.open"
    assert commands.needed("!case", "") == "case.read"


def test_a_refused_command_is_taken_down_and_explained(harness, monkeypatch):
    monkeypatch.setattr(commands.access, "may", lambda conn, user_id, capability, case=None: (False, "no"))
    slack = Slack()
    event = {"channel": CHANNEL_ID, "ts": "2.0", "user": "UME"}

    commands.reply(slack, event, THREAD, commands.run("!claim", "", 39, "UME"))

    assert harness["deleted"] == ["2.0"]
    assert slack.calls_to("chat_postEphemeral")[0]["text"] == "Not permitted: no"
    assert slack.calls_to("chat_postMessage") == []


def test_a_command_that_worked_is_replaced_by_its_line(harness):
    slack = Slack()
    event = {"channel": CHANNEL_ID, "ts": "2.0", "user": "UME"}

    commands.reply(slack, event, THREAD, commands.run("!claim", "", 39, "UME"))

    assert slack.calls_to("chat_postMessage")[0]["text"] == "<@UME> claimed case 39"
    assert harness["deleted"] == ["2.0"]


def test_a_note_stays_and_is_marked_saved(harness):
    slack = Slack()
    event = {"channel": CHANNEL_ID, "ts": "2.0", "user": "UME"}

    commands.reply(slack, event, THREAD, commands.run("!note", "spoke to them", 39, "UME"))

    assert slack.calls_to("reactions_add")[0]["name"] == "white_check_mark"
    assert harness["deleted"] == []


def test_a_refusal_nemo_cannot_take_down_is_crossed_instead(monkeypatch):
    def fail(channel_id, ts, max_retries=2):
        raise RuntimeError("proxy down")

    monkeypatch.setattr(commands.privileged, "delete_message", fail)
    slack = Slack()

    commands.delete_command(slack, CHANNEL_ID, "2.0", failed=True)

    assert slack.calls_to("reactions_add")[0]["name"] == "x"


def test_case_link_is_the_header(harness):
    assert commands.run("!case", "", 39, "UME")["say"] == ["Case 39"]
