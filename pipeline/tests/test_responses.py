import pytest

from bot.nemo import responses
from bot.nemo.surface import autoresponse, unsub_shield

USER_ID = "U1"
CHANNEL_ID = "CLOGS"
TS = "1700000000.000100"
THREAD = "1700000000.000000"

BODY = "here is why we do not name the reason"


class Conn:
    def __init__(self, rows=None, allows=True):
        self.rows = rows or []
        self.allows = allows
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return ("now",) if self.allows else None

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class Slack:
    def __init__(self, bot=False, deleted=False):
        self.bot = bot
        self.deleted = deleted
        self.posted = []
        self.ephemeral = []

    def users_info(self, **kwargs):
        return {"user": {"is_bot": self.bot, "deleted": self.deleted}}

    def chat_postMessage(self, **kwargs):
        self.posted.append(kwargs)
        return {"ts": "9.9"}

    def chat_postEphemeral(self, **kwargs):
        self.ephemeral.append(kwargs)
        return {"ok": True}


class Ctx:
    def __init__(self, event, client=None):
        self.payload = event
        self.client = client or Slack()


class _conn_context:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *failure):
        return False


@pytest.fixture(autouse=True)
def reset_settings():
    responses._settings.clear()
    responses._loaded = False
    yield
    responses._settings.clear()
    responses._loaded = False


def load(**over):
    settings = {
        responses.AUTORESPONSE_ON: "on",
        responses.AUTORESPONSE_EMOJI: "fd-reason,blunder",
        responses.AUTORESPONSE_CHANNEL: CHANNEL_ID,
        responses.AUTORESPONSE_BODY: BODY,
        responses.AUTORESPONSE_COOLDOWN: "7",
        responses.UNSUB_SHIELD_ON: "on",
        responses.UNSUB_SHIELD_LINK: "https://unsub.hack.club",
    }
    settings.update(over)
    responses.refresh(Conn(rows=list(settings.items())))


def reacted(emoji="fd-reason", **over):
    return {"user": USER_ID, "reaction": emoji,
            "item": {"type": "message", "channel": CHANNEL_ID, "ts": TS}, **over}


def posted(text="UNSUBSCRIBE", **over):
    return {"user": USER_ID, "channel": CHANNEL_ID, "ts": TS, "thread_ts": THREAD,
            "text": text, **over}


def test_applies_to_and_unsub_shield_before_settings_load_are_disabled():
    assert responses.applies_to(CHANNEL_ID, "fd-reason") is False
    assert responses.unsub_shield_enabled() is False


def test_send_autoresponse_matching_reaction_posts_body_to_member(monkeypatch):
    load()
    conn = Conn()
    client = Slack()
    monkeypatch.setattr(autoresponse, "session", lambda: _conn_context(conn))

    assert autoresponse.send_autoresponse(Ctx(reacted(), client)) == USER_ID
    assert client.posted[0]["channel"] == USER_ID
    assert client.posted[0]["text"] == BODY


def test_send_autoresponse_replaces_member_placeholder(monkeypatch):
    load(**{responses.AUTORESPONSE_BODY: "Hi {member}, here is why. {member}"})
    client = Slack()
    monkeypatch.setattr(autoresponse, "session", lambda: _conn_context(Conn()))

    autoresponse.send_autoresponse(Ctx(reacted(), client))

    assert client.posted[0]["text"] == f"Hi <@{USER_ID}>, here is why. <@{USER_ID}>"


def test_render_body_leaves_other_braces_unchanged():
    load(**{responses.AUTORESPONSE_BODY: "use {curly} as is, {member}"})

    assert responses.render_body("U9") == "use {curly} as is, <@U9>"


def test_render_body_before_settings_load_returns_empty(monkeypatch):
    monkeypatch.setattr(responses, "_loaded", False)

    assert responses.render_body("U9") == ""


def test_send_autoresponse_skin_tone_emoji_matches(monkeypatch):
    load()
    client = Slack()
    monkeypatch.setattr(autoresponse, "session", lambda: _conn_context(Conn()))
    autoresponse.send_autoresponse(Ctx(reacted("fd-reason::skin-tone-3"), client))

    assert client.posted


def test_send_autoresponse_other_emoji_returns_none(monkeypatch):
    load()
    client = Slack()
    monkeypatch.setattr(autoresponse, "session", lambda: _conn_context(Conn()))

    assert autoresponse.send_autoresponse(Ctx(reacted("tada"), client)) is None
    assert client.posted == []


def test_send_autoresponse_other_channel_returns_none(monkeypatch):
    load()
    client = Slack()
    monkeypatch.setattr(autoresponse, "session", lambda: _conn_context(Conn()))
    event = reacted()
    event["item"]["channel"] = "CELSE"

    assert autoresponse.send_autoresponse(Ctx(event, client)) is None
    assert client.posted == []


def test_send_autoresponse_disabled_returns_none(monkeypatch):
    load(**{responses.AUTORESPONSE_ON: "off"})
    client = Slack()
    monkeypatch.setattr(autoresponse, "session", lambda: _conn_context(Conn()))

    assert autoresponse.send_autoresponse(Ctx(reacted(), client)) is None


def test_send_autoresponse_empty_body_returns_none(monkeypatch):
    load(**{responses.AUTORESPONSE_BODY: ""})
    client = Slack()
    monkeypatch.setattr(autoresponse, "session", lambda: _conn_context(Conn()))

    assert autoresponse.send_autoresponse(Ctx(reacted(), client)) is None


def test_send_autoresponse_inside_cooldown_returns_none(monkeypatch):
    load()
    client = Slack()
    monkeypatch.setattr(autoresponse, "session", lambda: _conn_context(Conn(allows=False)))

    assert autoresponse.send_autoresponse(Ctx(reacted(), client)) is None
    assert client.posted == []


def test_send_autoresponse_bot_user_returns_none(monkeypatch):
    load()
    client = Slack(bot=True)
    monkeypatch.setattr(autoresponse, "session", lambda: _conn_context(Conn()))

    assert autoresponse.send_autoresponse(Ctx(reacted(), client)) is None
    assert client.posted == []


def test_send_autoresponse_inserts_cooldown_row_before_posting(monkeypatch):
    load()
    conn = Conn(allows=False)
    monkeypatch.setattr(autoresponse, "session", lambda: _conn_context(conn))
    autoresponse.send_autoresponse(Ctx(reacted()))

    assert conn.args_for("INSERT INTO fd.autoresponse_cooldown")


def test_cooldown_days_invalid_values_fall_back_to_seven():
    load(**{responses.AUTORESPONSE_COOLDOWN: "0"})
    assert responses.cooldown_days() == 7
    load(**{responses.AUTORESPONSE_COOLDOWN: "sideways"})
    assert responses.cooldown_days() == 7
    load(**{responses.AUTORESPONSE_COOLDOWN: "3"})
    assert responses.cooldown_days() == 3


def test_unsub_shield_on_message_removes_message_and_notifies_with_link(monkeypatch):
    load()
    client = Slack()
    removed = []
    monkeypatch.setattr(unsub_shield.guard_actions, "remove",
                        lambda _c, channel_id, ts: removed.append((channel_id, ts)))

    assert unsub_shield.on_message(Ctx(posted(), client)) is True
    assert removed == [(CHANNEL_ID, TS)]
    assert "unsub.hack.club" in client.ephemeral[0]["text"]
    assert client.ephemeral[0]["thread_ts"] == THREAD


def test_unsub_shield_on_message_without_link_omits_see_how(monkeypatch):
    load(**{responses.UNSUB_SHIELD_LINK: ""})
    client = Slack()
    monkeypatch.setattr(unsub_shield.guard_actions, "remove", lambda *a: True)
    unsub_shield.on_message(Ctx(posted(), client))

    assert "See how" not in client.ephemeral[0]["text"]


def test_unsub_shield_on_message_matches_lowercase_with_spaces(monkeypatch):
    load()
    removed = []
    monkeypatch.setattr(unsub_shield.guard_actions, "remove",
                        lambda _c, channel_id, ts: removed.append((channel_id, ts)))
    unsub_shield.on_message(Ctx(posted("  unsubscribe  ")))

    assert removed == [(CHANNEL_ID, TS)]


def test_unsub_shield_on_message_inline_mention_returns_none(monkeypatch):
    load()
    removed = []
    monkeypatch.setattr(unsub_shield.guard_actions, "remove",
                        lambda _c, channel_id, ts: removed.append((channel_id, ts)))

    assert unsub_shield.on_message(Ctx(posted("how do I UNSUBSCRIBE from this"))) is None
    assert removed == []


def test_unsub_shield_on_message_outside_thread_returns_none(monkeypatch):
    load()
    removed = []
    monkeypatch.setattr(unsub_shield.guard_actions, "remove",
                        lambda _c, channel_id, ts: removed.append((channel_id, ts)))

    assert unsub_shield.on_message(Ctx(posted(thread_ts=None))) is None
    assert removed == []


def test_unsub_shield_on_message_disabled_returns_none(monkeypatch):
    load(**{responses.UNSUB_SHIELD_ON: "off"})
    removed = []
    monkeypatch.setattr(unsub_shield.guard_actions, "remove",
                        lambda _c, channel_id, ts: removed.append((channel_id, ts)))

    assert unsub_shield.on_message(Ctx(posted())) is None
    assert removed == []
