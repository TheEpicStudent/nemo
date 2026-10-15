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


def edited(text, **over):
    return {
        "subtype": "message_changed",
        "channel": CHANNEL_ID,
        "ts": "1700000009.000000",
        "message": {"user": USER_ID, "ts": TS, "text": text, **over},
    }


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(userbots, "_people", {})
    automod._watching[:] = []
    automod._loaded = False
    yield
    automod._watching[:] = []
    automod._loaded = False


def load(*rows):
    conn = Conn(rows)
    automod.refresh(conn)
    return conn


def test_nothing_is_read_before_the_list_is_loaded():
    assert automod.watching() is None
    assert automod.caught("anything at all") == []


def test_a_whole_word_does_not_match_inside_another_word():
    load((1, "ass", "word", "flag", None))

    assert automod.caught("that was an ass move")
    assert automod.caught("she is classy") == []
    assert automod.caught("passing through") == []


def test_a_whole_word_matches_against_punctuation():
    load((1, "badword", "word", "flag", None))

    assert automod.caught("badword!")
    assert automod.caught("(badword)")
    assert automod.caught("...badword...")


def test_a_substring_matches_inside_a_word():
    load((1, "spam", "substring", "flag", None))

    assert automod.caught("antispamming")


def test_a_regex_matches_what_it_says():
    load((1, "ba+dword", "regex", "flag", None))

    assert automod.caught("baaadword")
    assert automod.caught("bdword") == []


def test_a_regex_that_backtracks_for_too_long_is_skipped_not_waited_on():
    load((1, "(a+)+$", "regex", "flag", None), (2, "fine", "word", "flag", None))

    assert automod.caught("a" * 40 + "!") == []
    assert automod.caught("all fine here")


def test_matching_ignores_case():
    load((1, "badword", "word", "flag", None))

    assert automod.caught("BadWord")


def test_a_regex_that_does_not_compile_is_left_out():
    load((1, "([a-z", "regex", "flag", None), (2, "fine", "word", "flag", None))

    assert len(automod.watching()) == 1
    assert automod.caught("fine")


def test_a_blank_word_is_left_out():
    load((1, "   ", "word", "flag", None))

    assert automod.watching() == []


def test_every_matching_word_is_caught():
    load((1, "one", "word", "flag", None), (2, "two", "word", "flag", None))

    assert len(automod.caught("one and two")) == 2


def test_refresh_replaces_what_was_held():
    load((1, "gone", "word", "flag", None))
    load((2, "fresh", "word", "flag", None))

    assert automod.caught("gone") == []
    assert automod.caught("fresh")


def test_a_match_is_recorded_with_the_message_kept():
    load((1, "badword", "word", "flag", "spam"))
    conn = Conn()
    watch = automod.caught("a badword here")[0]
    automod.record(conn, watch, message("a badword here"))

    match_row = conn.args_for("INSERT INTO fd.automod_matches")[0]
    assert match_row[1] == "badword"
    assert match_row[3] == USER_ID
    assert match_row[4] == CHANNEL_ID
    assert match_row[7] == "a badword here"


def test_the_watcher_records_what_it_catches(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))

    assert automod_watch.watched(Ctx(message("a badword here"))) == 1
    assert conn.args_for("INSERT INTO fd.automod_matches")


def test_the_watcher_leaves_a_clean_message_alone(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))

    assert automod_watch.watched(Ctx(message("nothing to see"))) is None
    assert not conn.args_for("INSERT INTO fd.automod_matches")


def test_the_watcher_ignores_a_bot(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))

    client = Slack(users={USER_ID: {"is_bot": True}})

    assert automod_watch.watched(Ctx(message("badword", bot_id="B1"), client)) is None
    assert not conn.args_for("INSERT INTO fd.automod_matches")


def test_watched_user_token_post_is_recorded(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))
    client = Slack(users={USER_ID: {"is_bot": False}})

    assert automod_watch.watched(Ctx(message("a badword here", bot_id="B1"), client)) == 1
    assert conn.args_for("INSERT INTO fd.automod_matches")[0][3] == USER_ID


def test_an_edit_that_adds_a_word_is_caught(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))

    assert automod_watch.watched(Ctx(edited("now with a badword"))) == 1
    match_row = conn.args_for("INSERT INTO fd.automod_matches")[0]
    assert match_row[5] == TS
    assert match_row[7] == "now with a badword"


def test_an_edit_records_against_the_message_not_the_edit():
    load((1, "badword", "word", "flag", None))
    normalized = automod_watch.message_in(edited("a badword"))

    assert normalized["ts"] == TS
    assert normalized["user"] == USER_ID
    assert normalized["channel"] == CHANNEL_ID


def test_a_clean_edit_records_nothing(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))

    assert automod_watch.watched(Ctx(edited("all tidied up now"))) is None
    assert not conn.args_for("INSERT INTO fd.automod_matches")


def test_an_edit_by_a_bot_is_left_alone(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))

    client = Slack(users={USER_ID: {"is_bot": True}})

    assert automod_watch.watched(Ctx(edited("badword", bot_id="B1"), client)) is None


def test_an_unfurl_that_matches_nothing_new_costs_no_permalink(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn(returns_id=False)
    client = Slack()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))
    automod_watch.watched(Ctx(edited("a badword here"), client))

    assert client.calls == []


def test_the_watcher_says_nothing_to_the_author(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn()
    client = Slack()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))
    automod_watch.watched(Ctx(message("a badword here"), client))

    assert not hasattr(client, "posted")
    assert not conn.args_for("DELETE")


def test_a_message_already_recorded_is_not_counted_twice(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn(returns_id=False)
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))

    assert automod_watch.watched(Ctx(message("a badword here"))) is None


def test_a_missing_permalink_does_not_stop_the_record(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))
    automod_watch.watched(Ctx(message("a badword here"), Slack(link=None)))

    assert conn.args_for("INSERT INTO fd.automod_matches")
    assert not conn.args_for("SET permalink")


def test_a_permalink_is_only_fetched_for_a_fresh_match(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn(returns_id=False)
    client = Slack()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))
    automod_watch.watched(Ctx(message("a badword here"), client))

    assert client.calls == []


def test_a_fresh_match_is_linked(monkeypatch):
    load((1, "badword", "word", "flag", None))
    conn = Conn()
    client = Slack()
    monkeypatch.setattr(automod_watch, "session", lambda: _conn_context(conn))
    automod_watch.watched(Ctx(message("a badword here"), client))

    assert client.calls == [{"channel": CHANNEL_ID, "message_ts": TS}]
    assert conn.args_for("SET permalink")[0][0] == client.link


class _conn_context:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *failure):
        return False
