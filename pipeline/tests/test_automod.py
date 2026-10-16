import pytest

from bot.nemo import automod, userbots
from bot.nemo.surface import automod_watch

USER_ID = "U1"
CHANNEL_ID = "C1"
TS = "1700000000.000100"


class Conn:
    def __init__(self, rows=(), returns_id=True):
        self.rows = list(rows)
        self.returns_id = returns_id
        self.executed = []
        self.next_id = 0

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        if not self.returns_id:
            return None
        self.next_id += 1
        return (self.next_id,)

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class Slack:
    def __init__(self, link="https://hackclub.slack.com/archives/C1/p1700000000000100", users=None):
        self.link = link
        self.calls = []
        self.users = users or {}

    def users_info(self, user):
        if user not in self.users:
            raise RuntimeError("user_not_found")
        return {"user": self.users[user]}

    def chat_getPermalink(self, **kwargs):
        self.calls.append(kwargs)
        if self.link is None:
            raise RuntimeError("no permalink")
        return {"permalink": self.link}


class Ctx:
    def __init__(self, event, client=None):
        self.payload = event
        self.client = client or Slack()


def message(text, **over):
    return {"user": USER_ID, "channel": CHANNEL_ID, "ts": TS, "text": text, **over}


def edit_event(text, **over):
    return {
        "subtype": "message_changed",
        "channel": CHANNEL_ID,
        "ts": "1700000009.000000",
        "message": {"user": USER_ID, "ts": TS, "text": text, **over},
    }


@pytest.fixture(autouse=True)
def reset_automod_state(monkeypatch):
    monkeypatch.setattr(userbots, "_users", {})
    automod._rules[:] = []
    automod._loaded = False
    yield
    automod._rules[:] = []
    automod._loaded = False


def load_rules(*rows):
    conn = Conn(rows)
    automod.refresh(conn)
    return conn


def test_active_rules_before_refresh_returns_none():
    assert automod.active_rules() is None
    assert automod.matching_rules("anything at all") == []


def test_matching_rules_word_rule_ignores_match_inside_other_word():
    load_rules((1, "ass", "word", "flag", None))

    assert automod.matching_rules("that was an ass move")
    assert automod.matching_rules("she is classy") == []
    assert automod.matching_rules("passing through") == []


def test_matching_rules_word_rule_matches_next_to_punctuation():
    load_rules((1, "badword", "word", "flag", None))

    assert automod.matching_rules("badword!")
    assert automod.matching_rules("(badword)")
    assert automod.matching_rules("...badword...")


def test_matching_rules_substring_rule_matches_inside_word():
    load_rules((1, "spam", "substring", "flag", None))

    assert automod.matching_rules("antispamming")


def test_matching_rules_regex_rule_matches_pattern():
    load_rules((1, "ba+dword", "regex", "flag", None))

    assert automod.matching_rules("baaadword")
    assert automod.matching_rules("bdword") == []


def test_matching_rules_regex_over_time_limit_is_skipped():
    load_rules((1, "(a+)+$", "regex", "flag", None), (2, "fine", "word", "flag", None))

    assert automod.matching_rules("a" * 40 + "!") == []
    assert automod.matching_rules("all fine here")


def test_matching_rules_ignores_case():
    load_rules((1, "badword", "word", "flag", None))

    assert automod.matching_rules("BadWord")


def test_refresh_invalid_regex_is_dropped():
    load_rules((1, "([a-z", "regex", "flag", None), (2, "fine", "word", "flag", None))

    assert len(automod.active_rules()) == 1
    assert automod.matching_rules("fine")


def test_refresh_blank_word_is_dropped():
    load_rules((1, "   ", "word", "flag", None))

    assert automod.active_rules() == []


def test_matching_rules_returns_every_matching_rule():
    load_rules((1, "one", "word", "flag", None), (2, "two", "word", "flag", None))

    assert len(automod.matching_rules("one and two")) == 2


def test_refresh_replaces_previous_rules():
    load_rules((1, "gone", "word", "flag", None))
    load_rules((2, "fresh", "word", "flag", None))

    assert automod.matching_rules("gone") == []
    assert automod.matching_rules("fresh")


def test_record_inserts_match_row_with_message_text():
    load_rules((1, "badword", "word", "flag", "spam"))
    conn = Conn()
    rule = automod.matching_rules("a badword here")[0]
    automod.record(conn, rule, message("a badword here"))

    match_row = conn.args_for("INSERT INTO fd.automod_matches")[0]
    assert match_row[1] == "badword"
    assert match_row[3] == USER_ID
    assert match_row[4] == CHANNEL_ID
    assert match_row[7] == "a badword here"


def test_match_automod_rules_with_match_inserts_row(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))

    assert automod_watch.match_automod_rules(Ctx(message("a badword here"))) == 1
    assert conn.args_for("INSERT INTO fd.automod_matches")


def test_match_automod_rules_clean_message_returns_none(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))

    assert automod_watch.match_automod_rules(Ctx(message("nothing to see"))) is None
    assert not conn.args_for("INSERT INTO fd.automod_matches")


def test_match_automod_rules_bot_author_returns_none(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))

    client = Slack(users={USER_ID: {"is_bot": True}})

    assert automod_watch.match_automod_rules(Ctx(message("badword", bot_id="B1"), client)) is None
    assert not conn.args_for("INSERT INTO fd.automod_matches")


def test_match_automod_rules_user_token_post_with_bot_id_inserts_row(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))
    client = Slack(users={USER_ID: {"is_bot": False}})

    assert automod_watch.match_automod_rules(Ctx(message("a badword here", bot_id="B1"), client)) == 1
    assert conn.args_for("INSERT INTO fd.automod_matches")[0][3] == USER_ID


def test_match_automod_rules_edit_adding_word_inserts_row(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))

    assert automod_watch.match_automod_rules(Ctx(edit_event("now with a badword"))) == 1
    match_row = conn.args_for("INSERT INTO fd.automod_matches")[0]
    assert match_row[5] == TS
    assert match_row[7] == "now with a badword"


def test_message_from_event_edit_uses_original_message_fields():
    load_rules((1, "badword", "word", "flag", None))
    normalized = automod_watch.message_from_event(edit_event("a badword"))

    assert normalized["ts"] == TS
    assert normalized["user"] == USER_ID
    assert normalized["channel"] == CHANNEL_ID


def test_match_automod_rules_clean_edit_returns_none(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))

    assert automod_watch.match_automod_rules(Ctx(edit_event("all tidied up now"))) is None
    assert not conn.args_for("INSERT INTO fd.automod_matches")


def test_match_automod_rules_bot_edit_returns_none(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))

    client = Slack(users={USER_ID: {"is_bot": True}})

    assert automod_watch.match_automod_rules(Ctx(edit_event("badword", bot_id="B1"), client)) is None


def test_match_automod_rules_duplicate_edit_match_skips_permalink(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn(returns_id=False)
    client = Slack()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))
    automod_watch.match_automod_rules(Ctx(edit_event("a badword here"), client))

    assert client.calls == []


def test_match_automod_rules_does_not_post_or_delete(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn()
    client = Slack()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))
    automod_watch.match_automod_rules(Ctx(message("a badword here"), client))

    assert not hasattr(client, "posted")
    assert not conn.args_for("DELETE")


def test_match_automod_rules_already_recorded_message_returns_none(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn(returns_id=False)
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))

    assert automod_watch.match_automod_rules(Ctx(message("a badword here"))) is None


def test_match_automod_rules_permalink_error_still_inserts_row(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))
    automod_watch.match_automod_rules(Ctx(message("a badword here"), Slack(link=None)))

    assert conn.args_for("INSERT INTO fd.automod_matches")
    assert not conn.args_for("SET permalink")


def test_match_automod_rules_duplicate_message_skips_permalink(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn(returns_id=False)
    client = Slack()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))
    automod_watch.match_automod_rules(Ctx(message("a badword here"), client))

    assert client.calls == []


def test_match_automod_rules_new_match_sets_permalink(monkeypatch):
    load_rules((1, "badword", "word", "flag", None))
    conn = Conn()
    client = Slack()
    monkeypatch.setattr(automod_watch, "session", lambda: ConnContext(conn))
    automod_watch.match_automod_rules(Ctx(message("a badword here"), client))

    assert client.calls == [{"channel": CHANNEL_ID, "message_ts": TS}]
    assert conn.args_for("SET permalink")[0][0] == client.link


class ConnContext:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *exc_info):
        return False
