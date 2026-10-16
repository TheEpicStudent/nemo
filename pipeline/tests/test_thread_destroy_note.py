import json

from bot.nemo import guards, guard_actions
from bot.nemo.views import guard as card


def rich_text(text):
    return {
        "type": "rich_text",
        "elements": [
            {"type": "rich_text_section", "elements": [{"type": "text", "text": text}]}
        ],
    }


def view_state(reason="enough", note_checked=False, note=None):
    values = {card.REASON: {card.REASON: {"value": reason}}}
    if note_checked:
        values[card.NOTE] = {card.NOTE: {"selected_options": [card.note_option()]}}
    if note is not None:
        values[card.NOTE_TEXT] = {card.NOTE_TEXT: {"rich_text_value": note}}
    return {"values": values}


def block_ids(view):
    return [one.get("block_id") for one in view["blocks"]]


def test_destroy_view_without_note_checkbox_hides_note_text_field():
    view = card.destroy_view("C1", "100.000")

    assert card.NOTE in block_ids(view)
    assert card.NOTE_TEXT not in block_ids(view)


def test_destroy_view_with_note_checkbox_shows_note_text_field():
    values = card.submitted_values(view_state(note_checked=True))
    view = card.destroy_view("C1", "100.000", values=values)

    assert card.NOTE_TEXT in block_ids(view)


def test_destroy_view_with_submitted_values_preserves_reason():
    values = card.submitted_values(view_state(reason="a raid", note_checked=True))
    view = card.destroy_view("C1", "100.000", values=values)
    reason = next(one for one in view["blocks"] if one.get("block_id") == card.REASON)

    assert reason["element"]["initial_value"] == "a raid"


def test_destroy_view_with_submitted_values_preserves_note_text():
    note = rich_text("we removed this")
    values = card.submitted_values(view_state(note_checked=True, note=note))
    view = card.destroy_view("C1", "100.000", values=values)
    field = next(one for one in view["blocks"] if one.get("block_id") == card.NOTE_TEXT)

    assert field["element"]["initial_value"] == note


def test_destroy_view_note_toggle_is_optional_dispatch_action():
    view = card.destroy_view("C1", "100.000")
    toggle = next(one for one in view["blocks"] if one.get("block_id") == card.NOTE)

    assert toggle["dispatch_action"] is True
    assert toggle["optional"] is True


def test_validation_errors_checked_note_without_text_returns_error():
    values = card.submitted_values(view_state(note_checked=True))

    assert card.validation_errors(values) == {card.NOTE_TEXT: "Enter note text"}


def test_validation_errors_unchecked_note_returns_none():
    assert card.validation_errors(card.submitted_values(view_state())) is None


def test_validation_errors_checked_note_with_text_returns_none():
    values = card.submitted_values(view_state(note_checked=True, note=rich_text("we removed this")))

    assert card.validation_errors(values) is None


def test_note_text_flattens_rich_text_to_plain_text():
    values = card.submitted_values(view_state(note_checked=True, note=rich_text("we removed this")))

    assert card.note_text(values) == "we removed this"


class Conn:
    def __init__(self, rows=None):
        self.rows = rows or {}
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


def test_set_note_writes_rich_text_plain_text_and_guard_id():
    conn = Conn()
    note = rich_text("we removed this")
    guards.set_note(conn, 9, note, "we removed this")

    rich, text, guard_id = conn.args_for("SET note_rich")[0]
    assert json.loads(rich) == note
    assert text == "we removed this"
    assert guard_id == 9


class Client:
    def __init__(self, response=None, raises=False):
        self.response = response or {"ts": "100.500"}
        self.raises = raises
        self.posted = []

    def chat_postMessage(self, **kwargs):
        if self.raises:
            raise RuntimeError("channel_not_found")
        self.posted.append(kwargs)
        return self.response


def install_fakes(monkeypatch, note_row, note_posted_calls=None):
    conn = Conn()
    posted_calls = [] if note_posted_calls is None else note_posted_calls
    monkeypatch.setattr(guards, "note_for", lambda _conn, _gid: note_row)
    monkeypatch.setattr(guards, "note_posted",
                        lambda _conn, gid, ts: posted_calls.append((gid, ts)))
    monkeypatch.setattr(guard_actions, "session", lambda: _Session(conn))
    return conn


class _Session:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *_):
        return False


def test_post_note_without_note_returns_none_and_does_not_post(monkeypatch):
    install_fakes(monkeypatch, (None, None, None))
    client = Client()

    assert guard_actions.post_note(client, 9, "C1", "100.000", "UMOD") is None
    assert client.posted == []


def test_post_note_posts_in_thread_with_moderator_signature_and_records_ts(monkeypatch):
    note_posted_calls = []
    note = rich_text("we removed this")
    install_fakes(monkeypatch, (note, "we removed this", None), note_posted_calls)
    client = Client()

    ts = guard_actions.post_note(client, 9, "C1", "100.000", "UMOD")

    assert ts == "100.500"
    assert note_posted_calls == [(9, "100.500")]
    message = client.posted[0]
    assert message["thread_ts"] == "100.000"
    assert message["text"] == "we removed this"
    assert message["blocks"][0] == note
    assert "<@UMOD>" in message["blocks"][1]["elements"][0]["text"]


def test_post_note_already_posted_returns_existing_ts_without_posting(monkeypatch):
    install_fakes(monkeypatch, (rich_text("x"), "x", "100.400"))
    client = Client()

    assert guard_actions.post_note(client, 9, "C1", "100.000", "UMOD") == "100.400"
    assert client.posted == []


def test_post_note_slack_error_returns_none(monkeypatch):
    install_fakes(monkeypatch, (rich_text("x"), "x", None))
    client = Client(raises=True)

    assert guard_actions.post_note(client, 9, "C1", "100.000", "UMOD") is None


def messages(*stamps):
    return [{"ts": ts} for ts in stamps]


def test_unremoved_timestamps_excludes_note_timestamp():
    values = messages("100.000", "100.100", "100.500", "100.200")

    assert guard_actions.unremoved_timestamps(values, "100.000", "100.500") == ["100.100", "100.200"]


def test_unremoved_timestamps_with_root_and_note_only_returns_root():
    values = messages("100.000", "100.500")

    assert guard_actions.unremoved_timestamps(values, "100.000", "100.500") == ["100.000"]


def test_unremoved_timestamps_without_note_returns_root_only_when_no_replies():
    values = messages("100.000", "100.100")

    assert guard_actions.unremoved_timestamps(values, "100.000") == ["100.100"]
    assert guard_actions.unremoved_timestamps(messages("100.000"), "100.000") == ["100.000"]


def test_destroy_view_first_block_is_sign_out_context():
    view = card.destroy_view("C1", "100.000")

    assert view["blocks"][0] == card.context_block()
