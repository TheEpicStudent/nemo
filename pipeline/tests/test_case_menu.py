import contextlib

import pytest

from bot.nemo import case_actions, channel, command, handlers
from bot.nemo.views import edit, merge


class App:
    def __init__(self):
        self.actions = {}
        self.views = {}

    def action(self, key):
        def keep(fn):
            self.actions[getattr(key, "pattern", key)] = fn
            return fn
        return keep

    def view(self, key):
        def keep(fn):
            self.views[key] = fn
            return fn
        return keep


class Conn:
    def __init__(self, answers):
        self.answers = answers
        self.ran = []

    def execute(self, sql, args=None):
        self.ran.append((sql, args))
        return self

    def fetchone(self):
        for mark, row in self.answers.items():
            if mark in self.ran[-1][0]:
                return row
        return None

    def fetchall(self):
        row = self.fetchone()
        return [row] if row else []


class Slack:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        return lambda **kwargs: self.calls.append((name, kwargs)) or {"ts": "9.9"}

    def made(self, name):
        return [kwargs for called, kwargs in self.calls if called == name]


class Ack:
    def __init__(self):
        self.said = []

    def __call__(self, **kwargs):
        self.said.append(kwargs)


ON_CARD = {"user": {"id": "UME"}, "trigger_id": "T1", "channel": {"id": "C_FIRE"},
           "message": {"ts": "1.0"}}
IN_MORE = {"user": {"id": "UME"}, "trigger_id": "T2", "view": {"id": "V1", "hash": "H1"}}


@pytest.fixture
def app(monkeypatch):
    built = App()
    handlers.register(built)
    conn = Conn({"resolved_at IS NULL": (True,), "category_key FROM": (None,)})

    @contextlib.contextmanager
    def one_session():
        yield conn

    monkeypatch.setattr(handlers, "session", one_session)
    monkeypatch.setattr(handlers.access, "may", lambda conn, who, needs, case=None: (True, None))
    monkeypatch.setattr(handlers, "live_actions", lambda conn, case_id: [])
    monkeypatch.setattr(handlers, "refresh_card", lambda client, conn, case_id: None)
    return built


def picked(verb, case_id=23):
    return {"actions": [{"selected_option": {"value": f"{verb}:{case_id}"}}]}


def pressed(verb, case_id=23):
    return {"actions": [{"value": f"{verb}:{case_id}"}]}


def test_a_pick_from_the_card_menu_opens_its_modal(app):
    slack = Slack()

    app.actions[edit.MENU](Ack(), dict(ON_CARD, **picked(edit.LOG_ACTION)), slack)

    assert slack.made("views_open")[0]["view"]["private_metadata"] == "23"


def test_more_opens_the_rest_of_the_case_actions(app):
    slack = Slack()

    app.actions[edit.MENU](Ack(), dict(ON_CARD, **picked(edit.MORE)), slack)

    view = slack.made("views_open")[0]["view"]
    labels = [one["text"]["text"] for one in view["blocks"][-1]["elements"]]
    assert labels == ["People", "Set the violation", "Merge"]


def test_a_pick_inside_more_stacks_its_modal_on_top(app, monkeypatch):
    monkeypatch.setattr(handlers, "mergeable", lambda conn, wanted: [(23, None, "bob"),
                                                                     (25, "spam", None)])
    slack = Slack()

    app.actions[f"^{edit.MORE_PICK}_"](Ack(), dict(IN_MORE, **pressed(edit.MERGE)), slack)

    view = slack.made("views_push")[0]["view"]
    assert view["callback_id"] == merge.CALLBACK
    assert view["blocks"][0]["element"]["initial_option"]["value"] == "23"
    assert slack.made("views_open") == []


def test_a_refusal_on_the_card_is_said_only_to_whoever_asked(app, monkeypatch):
    monkeypatch.setattr(handlers.access, "may", lambda conn, who, needs, case=None: (False, "no"))
    slack = Slack()

    app.actions[edit.MENU](Ack(), dict(ON_CARD, **picked(edit.RESOLVE)), slack)

    assert slack.made("chat_postEphemeral")[0]["text"] == "no"
    assert slack.made("views_open") == []


def test_a_refusal_inside_more_is_shown_in_more(app, monkeypatch):
    monkeypatch.setattr(handlers.access, "may", lambda conn, who, needs, case=None: (False, "no"))
    slack = Slack()

    app.actions[f"^{edit.MORE_PICK}_"](Ack(), dict(IN_MORE, **pressed(edit.REVERSE)), slack)

    shown = slack.made("views_update")[0]
    assert shown["view_id"] == "V1"
    assert shown["view"]["blocks"][0]["elements"][0]["text"] == "no"


def test_claiming_from_the_menu_puts_you_on_the_case(app, monkeypatch):
    held = []
    monkeypatch.setattr(handlers, "claimed", lambda conn, case_id, who: held.append((case_id, who)))

    app.actions[edit.MENU](Ack(), dict(ON_CARD, **picked(edit.CLAIM)), Slack())

    assert held == [(23, "UME")]


def test_the_old_buttons_still_work_on_cards_drawn_before(app):
    slack = Slack()

    app.actions[edit.LOG_ACTION](Ack(), dict(ON_CARD, actions=[{"value": "23"}]), slack)

    assert slack.made("views_open")


def merging(keep, *fold):
    chosen = [{"value": str(one)} for one in fold]
    return {"state": {"values": {
        merge.KEEP: {merge.KEEP: {"selected_option": {"value": str(keep)}}},
        merge.FOLD: {merge.FOLD: {"selected_options": chosen}},
    }}}


def test_merging_closes_the_rest_into_the_one_kept(app, monkeypatch):
    noted = []
    monkeypatch.setattr(handlers, "merge", lambda conn, keep, fold, by: fold)
    monkeypatch.setattr(handlers, "post_merge_note",
                        lambda client, conn, keep, closed: noted.append((keep, closed)))
    ack = Ack()

    app.views[merge.CALLBACK](ack, {"user": {"id": "UME"}}, merging(23, 25, 31), Slack())

    assert ack.said == [{"response_action": "clear"}]
    assert noted == [(23, [25, 31])]


def test_a_case_cannot_merge_into_itself(app):
    ack = Ack()

    app.views[merge.CALLBACK](ack, {"user": {"id": "UME"}}, merging(23, 23), Slack())

    assert ack.said[0]["errors"] == {merge.FOLD: "The case you keep cannot close into itself."}


def test_case_numbers_after_merge_are_kept_then_folded():
    assert merge.asked("23 25, #31") == (23, [25, 31])
    assert merge.asked("") == (None, [])
    assert command.asked("merge 23 25") == ("merge", None, "23 25")
    assert command.NEEDED[command.MERGE] == "case.resolve"


def test_a_merged_case_closes_as_a_duplicate_and_is_audited():
    conn = Conn({"duplicate_of = %s": ("2026-10-11",)})

    assert case_actions.merge(conn, 23, [31, 25], "UME") == [25, 31]

    closing = [args for sql, args in conn.ran if "duplicate_of = %s" in sql]
    assert closing == [(23, 25, 23), (23, 31, 23)]
    audits = [args for sql, args in conn.ran if "audit" in sql.lower()]
    assert len(audits) == 2


def test_a_case_already_resolved_is_left_out_of_the_merge():
    assert case_actions.merge(Conn({}), 23, [25], "UME") == []


def test_the_kept_case_hears_what_was_merged_into_it():
    assert channel.merged_text([25]) == "case 25 merged into this one"
    assert channel.merged_text([25, 31]) == "cases 25, 31 merged into this one"


def resolving():
    return {"private_metadata": "23", "state": {"values": {}}}


def test_a_resolve_that_tells_the_reporter_holds_its_line_for_after(app, monkeypatch):
    held, echoed = [], []
    monkeypatch.setattr(handlers.views.resolve, "submitted_values",
                        lambda state, live: {"resolution": "no_action", "member_note": None,
                                             "message": "thanks", "notify_reporter": True})
    monkeypatch.setattr(handlers.views.resolve, "validation_errors", lambda values: None)
    monkeypatch.setattr(handlers, "resolve", lambda conn, case_id, values, by: 1)
    monkeypatch.setattr(handlers, "hold_resolution_echo",
                        lambda conn, case_id, by: held.append((case_id, by)))
    monkeypatch.setattr(handlers, "post_resolution_echo", lambda *args: echoed.append(args))

    app.views[handlers.views.resolve.CALLBACK](Ack(), {"user": {"id": "UME"}}, resolving(), Slack())

    assert held == [(23, "UME")]
    assert echoed == []


def test_a_quiet_resolve_says_so_at_once(app, monkeypatch):
    held, echoed = [], []
    monkeypatch.setattr(handlers.views.resolve, "submitted_values",
                        lambda state, live: {"resolution": "no_action", "member_note": None,
                                             "message": None, "notify_reporter": False})
    monkeypatch.setattr(handlers.views.resolve, "validation_errors", lambda values: None)
    monkeypatch.setattr(handlers, "resolve", lambda conn, case_id, values, by: 0)
    monkeypatch.setattr(handlers, "hold_resolution_echo",
                        lambda conn, case_id, by: held.append((case_id, by)))
    monkeypatch.setattr(handlers, "resolution_echo_actions", lambda conn, case_id: [])
    monkeypatch.setattr(handlers, "post_resolution_echo", lambda *args: echoed.append(args))

    app.views[handlers.views.resolve.CALLBACK](Ack(), {"user": {"id": "UME"}}, resolving(), Slack())

    assert held == []
    assert len(echoed) == 1


def test_a_held_line_goes_up_once_the_reporter_message_is_in(monkeypatch):
    from bot.nemo import case_channel

    posted = []

    @contextlib.contextmanager
    def one_session():
        yield Conn({})

    monkeypatch.setattr(case_channel, "session", one_session)
    monkeypatch.setattr(case_channel.case_actions, "held_resolution_echoes", lambda conn: [23, 24])
    monkeypatch.setattr(case_channel.case_actions, "resolution_echo_due",
                        lambda conn, case_id: ("UME", "no_action", None) if case_id == 23 else None)
    monkeypatch.setattr(case_channel.case_actions, "resolution_echo_actions", lambda conn, case_id: [])
    monkeypatch.setattr(case_channel.channel, "post_resolution_echo",
                        lambda client, conn, case_id, resolution, note, by, actions:
                        posted.append((case_id, resolution, by)))

    case_channel.CaseChannel(Slack()).post_held_resolutions()

    assert posted == [(23, "no_action", "UME")], "24 still waits on its reporter message"


def test_the_line_is_due_only_when_no_reporter_message_is_left_to_echo():
    assert "o.kind = 'outcome' AND o.echoed_at IS NULL" in case_actions.RESOLUTION_ECHO_DUE
    assert "SET resolution_echo_by = NULL" in case_actions.RESOLUTION_ECHO_DUE
