import contextlib

import pytest

from bot.nemo.surface import reaction_watch

BOT_ID = "UNEMO"
CHANNEL_ID = "C_FIRE"
MODERATOR_ID = "UMODERATOR"
TARGET_ID = "UTARGET"
REPORT_CARD_TS = "100.000"
REPLY_TS = "100.500"
REPORT_CASE_ID = 23
NEW_CASE_ID = 77
REPORT_THREAD_SQL = "AND forwarded_ts = %s"


class Conn:
    def __init__(self, rows):
        self.rows = rows
        self.last_sql = ""

    def execute(self, sql, args=None):
        self.last_sql = sql
        return self

    def fetchone(self):
        for marker, row in self.rows.items():
            if marker in self.last_sql:
                return row
        return None

    def fetchall(self):
        row = self.fetchone()
        return [row] if row else []


class Ctx:
    def __init__(self, payload):
        self.payload = payload
        self.client = object()


def reaction(name, ts):
    return Ctx({"reaction": name, "user": MODERATOR_ID,
                "item": {"type": "message", "channel": CHANNEL_ID, "ts": ts}})


@pytest.fixture
def reaction_calls(monkeypatch):
    calls = {"opened": [], "prompted": [], "closed": [], "rows": {}}

    @contextlib.contextmanager
    def fake_session():
        yield Conn(calls["rows"])

    monkeypatch.setattr(reaction_watch, "session", fake_session)
    monkeypatch.setattr(reaction_watch.whoami, "bot_user_id", lambda client, name: BOT_ID)
    monkeypatch.setattr(reaction_watch.channels, "react_channels", lambda conn: {CHANNEL_ID})
    monkeypatch.setattr(reaction_watch.access, "may",
                        lambda conn, user_id, capability, case=None: (True, None))
    monkeypatch.setattr(reaction_watch, "root_of",
                        lambda client, channel_id, ts: (REPORT_CARD_TS, {"user": TARGET_ID}))
    monkeypatch.setattr(reaction_watch.case_actions, "open_case",
                        lambda conn, subject, body, by: calls["opened"].append(by) or NEW_CASE_ID)
    monkeypatch.setattr(reaction_watch, "store_root_message",
                        lambda conn, case_id, channel_id, message: None)
    monkeypatch.setattr(reaction_watch.case_queue, "post",
                        lambda client, conn, case_id, channel_id, thread_ts: None)
    monkeypatch.setattr(reaction_watch, "post_ban_prompt",
                        lambda client, conn, case_id, target: calls["prompted"].append((case_id, target)))
    monkeypatch.setattr(reaction_watch.case_actions, "close_quietly",
                        lambda conn, case_id, resolution, by: calls["closed"].append(case_id))
    monkeypatch.setattr(reaction_watch, "after_resolve", lambda *args, **kwargs: None)
    return calls


def test_open_reaction_on_report_thread_returns_existing_case(reaction_calls):
    reaction_calls["rows"][REPORT_THREAD_SQL] = (REPORT_CASE_ID,)

    assert reaction_watch.open_case_on_reaction(reaction("hourglass", REPORT_CARD_TS)) == REPORT_CASE_ID
    assert reaction_calls["opened"] == []


def test_open_reaction_on_thread_without_case_opens_case(reaction_calls):
    assert reaction_watch.open_case_on_reaction(reaction("hourglass", REPORT_CARD_TS)) == NEW_CASE_ID
    assert reaction_calls["opened"] == [MODERATOR_ID]


def test_ban_on_report_thread_reply_prompts_existing_case(reaction_calls):
    reaction_calls["rows"][REPORT_THREAD_SQL] = (REPORT_CASE_ID,)

    assert reaction_watch.banned(reaction("ban", REPLY_TS)) == REPORT_CASE_ID
    assert reaction_calls["prompted"] == [(REPORT_CASE_ID, TARGET_ID)]
    assert reaction_calls["opened"] == []


def test_resolve_reaction_on_report_thread_reply_is_ignored(reaction_calls):
    reaction_calls["rows"][REPORT_THREAD_SQL] = (REPORT_CASE_ID,)

    assert reaction_watch.close_case_on_root_reaction(reaction("white_check_mark", REPLY_TS)) is None
    assert reaction_calls["closed"] == []


CASE_THREAD_SQL = "AND card_thread_ts = %s"
ROOT_TS = "200.000"
REPLY_IN_CASE_THREAD_TS = "200.500"
THREAD_CASE_ID = 31


class RootTsConn(Conn):
    def execute(self, sql, args=None):
        self.last_sql = sql if not args or ROOT_TS in args else ""
        return self


@pytest.fixture
def case_thread_calls(reaction_calls, monkeypatch):
    reaction_calls["rows"][CASE_THREAD_SQL] = (THREAD_CASE_ID,)

    @contextlib.contextmanager
    def fake_session():
        yield RootTsConn(reaction_calls["rows"])

    def fail_root_lookup(*args):
        raise AssertionError("root_of called")

    monkeypatch.setattr(reaction_watch, "session", fake_session)
    monkeypatch.setattr(reaction_watch, "root_of", fail_root_lookup)
    monkeypatch.setattr(reaction_watch.case_actions, "close_quietly",
                        lambda conn, case_id, resolution, by: reaction_calls["closed"].append(case_id)
                        or (resolution or "no_action"))
    return reaction_calls


@pytest.mark.parametrize("reaction_name", ["white_check_mark", "white_tick", "check", "check-green", "x"])
def test_close_reaction_on_case_thread_root_closes_case(case_thread_calls, reaction_name):
    assert reaction_watch.close_case_on_root_reaction(reaction(reaction_name, ROOT_TS)) == THREAD_CASE_ID
    assert case_thread_calls["closed"] == [THREAD_CASE_ID]


@pytest.mark.parametrize("reaction_name", ["white_check_mark", "x"])
def test_close_reaction_on_case_thread_reply_is_ignored(case_thread_calls, reaction_name):
    assert reaction_watch.close_case_on_root_reaction(reaction(reaction_name, REPLY_IN_CASE_THREAD_TS)) is None
    assert case_thread_calls["closed"] == []


@pytest.mark.parametrize(("reaction_name", "is_resolve", "is_close"), [
    ("white_check_mark", True, True),
    ("heavy_check_mark", True, True),
    ("ballot_box_with_check", True, True),
    ("white_tick", True, True),
    ("check", True, True),
    ("check-green", True, True),
    ("check-", False, False),
    ("checkered_flag", False, False),
    ("x", False, True),
    ("eyes", False, False),
])
def test_reaction_name_classification(reaction_name, is_resolve, is_close):
    assert reaction_watch.is_resolve_reaction(reaction_name) is is_resolve
    assert reaction_watch.is_close_reaction(reaction_name) is is_close
