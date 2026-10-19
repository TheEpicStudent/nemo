import contextlib
import datetime as dt

import pytest

from bot.core.formatting import short_end, short_end_token
from bot.nemo import channels, internal_log, public_log
from bot.nemo.views.activity import message_url

END = dt.datetime(2026, 10, 17, 14, 30, tzinfo=dt.UTC)
THREAD = "1700000000.000100"


def entry(verb, actor="UMOD", entity_type="member_guard"):
    return {"id": 1, "actor": actor, "entity_type": entity_type, "entity_id": 7, "verb": verb,
            "before": None, "after": None}


SHUSH = ("shush", "U1", None, "spam", END)
BAN = ("channel_ban", "U1", "C1", None, None)
DEACTIVATION = ("deactivation", "U1", None, "alt", None)
LOCK = ("lock", "C1", THREAD, "raid", END, "running", "UMOD", 0)
DESTROY = ("destroy", "C1", THREAD, "raid", None, "done", "UMOD", 42)


@pytest.mark.parametrize(("row", "made", "event", "values"), [
    (SHUSH, entry("opened"), "shush",
     {"member": "<@U1>", "admin": "<@UMOD>", "channel": "", "reason": "spam", "ends": f"until {short_end_token(END)}"}),
    (BAN, entry("opened", actor="nemo"), "channel_ban",
     {"member": "<@U1>", "admin": "Nemo", "channel": "<#C1>", "reason": "n/a", "ends": "with no end date"}),
    (DEACTIVATION, entry("opened"), "deactivation", {"member": "<@U1>", "reason": "alt"}),
    (SHUSH, entry("lifted"), None, None),
    (("unknown",) + SHUSH[1:], entry("opened"), None, None),
])
def test_member_values_map_guard_kind_to_event(row, made, event, values):
    found, found_values = public_log.member_values(made, row)

    assert found == event
    assert all(found_values[key] == value for key, value in (values or {}).items())


@pytest.mark.parametrize(("row", "made", "event"), [
    (LOCK, entry("opened", entity_type="thread_guard"), "lock"),
    (LOCK, entry("lifted", entity_type="thread_guard"), None),
    (DESTROY, entry("lifted", actor="system", entity_type="thread_guard"), "destroy"),
    (DESTROY, entry("opened", entity_type="thread_guard"), None),
    (DESTROY[:5] + ("failed", "UMOD", 3), entry("lifted", entity_type="thread_guard"), None),
])
def test_thread_values_map_lock_and_destroy_to_event(row, made, event):
    assert public_log.thread_values(made, row)[0] == event


def test_thread_values_for_lock_and_destroy_carry_template_variables():
    lock = public_log.thread_values(entry("opened", entity_type="thread_guard"), LOCK)[1]
    destroy = public_log.thread_values(entry("lifted", actor="system", entity_type="thread_guard"), DESTROY)[1]

    assert lock == {"admin": "<@UMOD>", "channel": "<#C1>", "thread": message_url("C1", THREAD),
                    "reason": "raid", "ends": f"until {short_end_token(END)}"}
    assert destroy["admin"] == "<@UMOD>" and destroy["count"] == 42 and destroy["channel"] == "<#C1>"
    assert destroy["thread"] == message_url("C1", THREAD)


def test_default_templates_put_the_thread_link_on_the_second_line():
    settings = {}
    lock = public_log.render(public_log.template_for(settings, "lock"), {
        "admin": "<@U1>", "channel": "<#C1>", "ends": "until 25 Oct", "reason": "raid", "thread": "https://t/1"})
    destroy = public_log.render(public_log.template_for(settings, "destroy"), {
        "admin": "<@U1>", "channel": "<#C1>", "count": 3, "thread": "https://t/1"})

    assert lock == "<@U1> locked a thread in <#C1> until 25 Oct. Reason: raid.\nhttps://t/1"
    assert destroy == "<@U1> destroyed a thread in <#C1> (3 messages)\nhttps://t/1"


def test_render_replaces_known_variables_and_keeps_unknown():
    assert public_log.render("{admin} did {action} in {channel}", {"admin": "<@U1>", "channel": "<#C1>"}) == \
        "<@U1> did {action} in <#C1>"


def test_default_templates_use_only_declared_variables():
    for key, definition in public_log.EVENTS.items():
        used = set(public_log.VARIABLE.findall(definition["template"]))
        assert used <= set(definition["variables"]), key


def test_is_enabled_follows_setting_then_default():
    assert public_log.is_enabled({}, "lock") is True
    assert public_log.is_enabled({}, "shush") is False
    assert public_log.is_enabled({public_log.enabled_key("shush"): "on"}, "shush") is True
    assert public_log.is_enabled({public_log.enabled_key("lock"): "off"}, "lock") is False


def test_template_for_prefers_custom_template_over_default():
    custom = {public_log.template_key("lock"): " {admin} locked {thread} "}

    assert public_log.template_for(custom, "lock") == "{admin} locked {thread}"
    assert public_log.template_for({public_log.template_key("lock"): " "}, "lock") == \
        public_log.EVENTS["lock"]["template"]


class Conn:
    def __init__(self, entries=(), rows=None, settings=None):
        self.entries = list(entries)
        self.rows = rows or {}
        self.settings = settings or {}
        self.cursor_moves = []
        self.sql = None

    def execute(self, sql, args=None):
        self.sql, self.args = sql, args
        if sql == internal_log.MOVE_CURSOR:
            self.cursor_moves.append(args)
        return self

    def fetchone(self):
        if self.sql == internal_log.CURSOR:
            return (10,)
        return self.rows.get(self.sql)

    def fetchall(self):
        if self.sql == public_log.SETTINGS_BY_KEY:
            return list(self.settings.items())
        return self.entries


class Slack:
    def __init__(self, fails=False):
        self.fails = fails
        self.posted = []

    def chat_postMessage(self, **kwargs):
        if self.fails:
            raise RuntimeError("ratelimited")
        self.posted.append(kwargs)


LOCK_ENTRY = (11, "UMOD", "thread_guard", 7, "opened", None, None)
SHUSH_ENTRY = (12, "UMOD", "member_guard", 8, "opened", None, None)
ROWS = {public_log.THREAD_GUARD: LOCK, public_log.MEMBER_GUARD: SHUSH}


def drain_with(monkeypatch, conn, client):
    @contextlib.contextmanager
    def session_of():
        yield conn

    guarded = []
    monkeypatch.setattr(public_log, "session", session_of)
    monkeypatch.setattr(internal_log, "session", session_of)
    monkeypatch.setattr(public_log, "ensure_read_only", lambda client, conn, channel_id: guarded.append(channel_id))
    return public_log.drain(client), guarded


def test_drain_posts_enabled_events_only_and_moves_cursor(monkeypatch):
    conn = Conn([LOCK_ENTRY, SHUSH_ENTRY], ROWS, {channels.PUBLIC_LOG: "CPUB"})
    client = Slack()

    handled, guarded = drain_with(monkeypatch, conn, client)

    assert handled == 2
    assert [one["channel"] for one in client.posted] == ["CPUB"]
    assert client.posted[0]["text"].startswith("<@UMOD> locked a thread in <#C1> until ")
    assert guarded == ["CPUB"]
    assert conn.cursor_moves == [(11, public_log.CURSOR_NAME), (12, public_log.CURSOR_NAME)]


def test_drain_uses_custom_template_and_enabled_override(monkeypatch):
    settings = {channels.PUBLIC_LOG: "CPUB", public_log.enabled_key("shush"): "on",
                public_log.template_key("shush"): "{member} was shushed by {admin}: {reason}"}
    conn = Conn([SHUSH_ENTRY], ROWS, settings)
    client = Slack()

    drain_with(monkeypatch, conn, client)

    assert [one["text"] for one in client.posted] == ["<@U1> was shushed by <@UMOD>: spam"]


def test_drain_without_channel_moves_cursor_without_posting(monkeypatch):
    conn = Conn([LOCK_ENTRY], ROWS)
    client = Slack()

    handled, _guarded = drain_with(monkeypatch, conn, client)

    assert handled == 1
    assert client.posted == []
    assert conn.cursor_moves == [(11, public_log.CURSOR_NAME)]


def test_drain_with_failed_post_does_not_move_cursor(monkeypatch):
    conn = Conn([LOCK_ENTRY], ROWS, {channels.PUBLIC_LOG: "CPUB"})

    handled, _guarded = drain_with(monkeypatch, conn, Slack(fails=True))

    assert handled == 0
    assert conn.cursor_moves == []


def test_drain_skips_entries_without_a_row(monkeypatch):
    conn = Conn([LOCK_ENTRY], {}, {channels.PUBLIC_LOG: "CPUB"})
    client = Slack()

    handled, _guarded = drain_with(monkeypatch, conn, client)

    assert handled == 1
    assert client.posted == []


def test_logged_ends_uses_the_date_token_and_plain_text_when_there_is_no_end():
    from bot.nemo.views import lengths

    assert lengths.logged_ends(END) == f"until {short_end_token(END)}"
    assert lengths.logged_ends(None) == "with no end date"
    assert lengths.ends(END) == f"until {short_end(END)}"
