import contextlib

import pytest

from bot.nemo import thread_commands as commands

ROOM = "C_FIRE"
THREAD = "100.000"


class Conn:
    def __init__(self, held=()):
        self.held = list(held)
        self.ran = []

    def execute(self, sql, args=None):
        self.ran.append((sql, args))
        return self

    def fetchall(self):
        return [(one,) for one in self.held]


class Slack:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda **kwargs: self.calls.append((name, kwargs)) or {"ok": True}

    def made(self, name):
        return [kwargs for called, kwargs in self.calls if called == name]


@pytest.fixture
def wired(monkeypatch):
    heard = {"claimed": [], "assigned": [], "removed": [], "noted": [], "member": [],
             "deleted": []}
    conn = Conn()

    @contextlib.contextmanager
    def one_session():
        yield conn

    monkeypatch.setattr(commands, "session", one_session)
    monkeypatch.setattr(commands.access, "may", lambda conn, who, needs, case=None: (True, None))
    monkeypatch.setattr(commands.case_actions, "claimed",
                        lambda conn, case_id, who: heard["claimed"].append(who))
    monkeypatch.setattr(commands.case_actions, "assign_people",
                        lambda conn, case_id, users, by: heard["assigned"].append(users))
    monkeypatch.setattr(commands.case_actions, "remove_assignee",
                        lambda conn, case_id, user, by: heard["removed"].append(user))
    monkeypatch.setattr(commands.case_actions, "keep_note",
                        lambda conn, case_id, body, by: heard["noted"].append(body))
    monkeypatch.setattr(commands.case_actions, "member_note",
                        lambda conn, user, body, by: heard["member"].append((user, body)))
    monkeypatch.setattr(commands.privileged, "delete_message",
                        lambda channel_id, ts, max_retries=2: heard["deleted"].append(ts))
    monkeypatch.setattr(commands.channel, "case_url", lambda case_id: None)
    heard["conn"] = conn
    return heard


def test_commands_are_read_from_the_first_word():
    assert commands.asked("!claim") == ("!claim", "")
    assert commands.asked("!Assign <@UA>  <@UB>") == ("!assign", "<@UA>  <@UB>")
    assert commands.asked("  ?Resolve ") == ("resolve", "")
    assert commands.asked("!resolve") == ("resolve", "")
    assert commands.asked("?we are looking at it") == (None, None)
    assert commands.asked("!whatever") == (None, None)


def test_claiming_assigns_you(wired):
    outcome = commands.run("!claim", "", 39, "UME")
    assert wired["claimed"] == ["UME"]
    assert outcome["say"] == ["<@UME> claimed case 39"]


def test_claiming_a_case_you_have_is_refused(wired):
    wired["conn"].held = ["UME", "UOTHER"]
    outcome = commands.run("!claim", "", 39, "UME")
    assert outcome["refused"] == "You are already assigned to case 39"
    assert wired["claimed"] == []


def test_claiming_beside_somebody_else_works(wired):
    wired["conn"].held = ["UOTHER"]
    assert commands.run("!claim", "", 39, "UME")["refused"] is None


def test_assign_adds_only_who_is_not_on_it(wired):
    wired["conn"].held = ["UA"]
    outcome = commands.run("!assign", "<@UA> <@UB|bob>", 39, "UME")
    assert wired["assigned"] == [["UB"]]
    assert outcome["say"] == ["<@UME> assigned case 39 to <@UB>"]


def test_assign_with_nobody_new_or_nobody_named_is_refused(wired):
    wired["conn"].held = ["UA"]
    assert commands.run("!assign", "<@UA>", 39, "UME")["refused"] == (
        "<@UA> is already assigned to case 39")
    assert commands.run("!assign", "", 39, "UME")["refused"] == "Usage: `!assign @user`"


def test_unassign_takes_people_off(wired):
    wired["conn"].held = ["UA", "UME"]
    outcome = commands.run("!unassign", "<@UME>", 39, "UME")
    assert wired["removed"] == ["UME"]
    assert outcome["say"] == ["<@UME> unassigned themselves from case 39"]
    assert commands.run("!unassign", "<@UZ>", 39, "UME")["refused"] == (
        "<@UZ> is not assigned to case 39")


def test_a_note_lands_on_the_case_or_the_member(wired):
    case = commands.run("!note", "spoke to them", 39, "UME")
    member = commands.run("!note", "<@UA> keeps doing this", 39, "UME")
    assert wired["noted"] == ["spoke to them"]
    assert wired["member"] == [("UA", "keeps doing this")]
    assert case == member == {"say": [], "react": "white_check_mark", "keep": True,
                              "refused": None}
    assert commands.run("!note", "<@UA>", 39, "UME")["refused"].startswith("Usage")


def test_each_command_asks_for_its_own_permission():
    assert commands.needed("!note", "<@UA> text") == "member.note"
    assert commands.needed("!note", "text") == "case.note"
    assert commands.needed("!claim", "") == "case.open"
    assert commands.needed("!case", "") == "case.read"


def test_a_refused_command_is_taken_down_and_explained(wired, monkeypatch):
    monkeypatch.setattr(commands.access, "may", lambda conn, who, needs, case=None: (False, "no"))
    slack = Slack()
    event = {"channel": ROOM, "ts": "2.0", "user": "UME"}

    commands.reply(slack, event, THREAD, commands.run("!claim", "", 39, "UME"))

    assert wired["deleted"] == ["2.0"]
    assert slack.made("chat_postEphemeral")[0]["text"] == "Not permitted: no"
    assert slack.made("chat_postMessage") == []


def test_a_command_that_worked_is_replaced_by_its_line(wired):
    slack = Slack()
    event = {"channel": ROOM, "ts": "2.0", "user": "UME"}

    commands.reply(slack, event, THREAD, commands.run("!claim", "", 39, "UME"))

    assert slack.made("chat_postMessage")[0]["text"] == "<@UME> claimed case 39"
    assert wired["deleted"] == ["2.0"]


def test_a_note_stays_and_is_marked_saved(wired):
    slack = Slack()
    event = {"channel": ROOM, "ts": "2.0", "user": "UME"}

    commands.reply(slack, event, THREAD, commands.run("!note", "spoke to them", 39, "UME"))

    assert slack.made("reactions_add")[0]["name"] == "white_check_mark"
    assert wired["deleted"] == []


def test_a_refusal_nemo_cannot_take_down_is_crossed_instead(monkeypatch):
    def fail(channel_id, ts, max_retries=2):
        raise RuntimeError("proxy down")

    monkeypatch.setattr(commands.privileged, "delete_message", fail)
    slack = Slack()

    commands.forget(slack, ROOM, "2.0", failed=True)

    assert slack.made("reactions_add")[0]["name"] == "x"


def test_case_link_is_the_header(wired):
    assert commands.run("!case", "", 39, "UME")["say"] == ["Case 39"]
