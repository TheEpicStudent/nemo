import contextlib

import pytest

from bot.nemo import case_actions
from bot.nemo.surface import member_view as surface
from bot.nemo.views import case_menu, member_view

MOD = "UMOD"


class Client:
    def __init__(self):
        self.pushed = []

    def views_push(self, **kwargs):
        self.pushed.append(kwargs)


class Ctx:
    def __init__(self, value="UM", view=None):
        self.body = {"actions": [{"value": value}]}
        self.view = view or {}
        self.client = Client()
        self.user_id = MOD
        self.trigger_id = "T1"
        self.acked = []

    def ack(self, **kwargs):
        self.acked.append(kwargs)


def submitted(text, user_id="UM"):
    state = {"values": {member_view.NOTE_TEXT: {member_view.NOTE_TEXT: {"value": text}}}}
    return {"private_metadata": user_id, "state": state}


@pytest.fixture
def notes(monkeypatch):
    saved = []

    @contextlib.contextmanager
    def session():
        yield object()

    monkeypatch.setattr(surface, "session", session)
    monkeypatch.setattr(case_actions, "member_note", lambda conn, subject, body, by: saved.append((subject, body, by)))
    return saved


def test_open_member_note_pushes_note_view(notes):
    ctx = Ctx()

    surface.open_member_note(ctx)

    view = ctx.client.pushed[0]["view"]
    assert ctx.client.pushed[0]["trigger_id"] == "T1"
    assert view["callback_id"] == member_view.NOTE_CALLBACK and view["private_metadata"] == "UM"


def test_open_member_note_without_value_does_nothing(notes):
    ctx = Ctx(value="")

    assert surface.open_member_note(ctx) is None
    assert ctx.client.pushed == []


def test_submit_member_note_saves_note_and_clears(notes):
    ctx = Ctx(view=submitted("  likely an alternate  "))

    assert surface.submit_member_note(ctx) == "UM"

    assert notes == [("UM", "likely an alternate", MOD)]
    assert ctx.acked == [{"response_action": "clear"}]


def test_submit_member_note_blank_text_returns_error(notes):
    ctx = Ctx(view=submitted("   "))

    surface.submit_member_note(ctx)

    assert notes == []
    assert ctx.acked == [{"response_action": "errors", "errors": {member_view.NOTE_TEXT: surface.NO_NOTE}}]


def test_note_modal_uses_member_note_capability():
    from bot.nemo.surface import ENTRIES

    needs = {(one.kind, one.key): one.needs for one in ENTRIES}

    assert needs[("action", member_view.ADD_NOTE)] == "member.note"
    assert needs[("view", member_view.NOTE_CALLBACK)] == "member.note"


def test_submit_uses_case_menu_text_reader():
    assert case_menu.typed(submitted(" x ")["state"], member_view.NOTE_TEXT) == "x"
