import contextlib
import inspect
import threading
from types import SimpleNamespace

import pytest

from bot.nemo import channel, chat, loop


class Conn:
    def __init__(self, rows=None, lists=None):
        self.rows = rows or {}
        self.lists = lists or {}
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        for mark, row in self.rows.items():
            if mark in self.executed[-1][0]:
                return row
        return None

    def fetchall(self):
        for mark, rows in self.lists.items():
            if mark in self.executed[-1][0]:
                return rows
        return []

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


@pytest.fixture(autouse=True)
def reset_channel_cache(monkeypatch):
    monkeypatch.setattr(channel, "_settings", {})
    monkeypatch.setattr(channel, "_react", {})
    monkeypatch.setattr(channel, "_cards", {}, raising=False)


def settings(monkeypatch, firehouse="C_FIRE", reports=None, logs=None, react=("C_REACT",)):
    values = {channel.channels.FIREHOUSE: firehouse, channel.channels.REPORTS: reports,
              channel.channels.LOGS: logs}
    monkeypatch.setattr(channel.channels, "setting", lambda conn, key: values.get(key))
    monkeypatch.setattr(channel.channels, "react_channels", lambda conn: set(react))


def test_a_card_can_land_in_the_firehouse_or_a_react_channel(monkeypatch):
    settings(monkeypatch)
    assert channel.case_channels(Conn()) == {"C_FIRE", "C_REACT"}


def test_the_firehouse_alone_is_enough(monkeypatch):
    settings(monkeypatch, react=())
    assert channel.case_channels(Conn()) == {"C_FIRE"}


def test_the_channels_are_remembered_so_every_message_does_not_ask(monkeypatch):
    settings(monkeypatch)
    channel.case_channels(Conn())
    monkeypatch.setattr(channel.channels, "react_channels", lambda conn: 1 / 0)
    assert channel.case_channels() == {"C_FIRE", "C_REACT"}


CARD_ROWS = {"FROM fd.case_reports WHERE card_channel_id IS NOT NULL": [("C_OLDFIRE",), ("G01DBHPLK25",)]}


def test_case_channels_includes_card_channels_after_firehouse_moves(monkeypatch):
    settings(monkeypatch, firehouse="C_NEWFIRE")

    assert channel.case_channels(Conn(lists=CARD_ROWS)) == {"C_NEWFIRE", "C_REACT", "C_OLDFIRE", "G01DBHPLK25"}


def test_card_channels_reads_reports_and_cases():
    assert "FROM fd.case_reports WHERE card_channel_id IS NOT NULL" in channel.CARD_CHANNELS
    assert "FROM fd.cases WHERE card_channel_id IS NOT NULL" in channel.CARD_CHANNELS


def test_card_channels_are_cached_between_refreshes(monkeypatch):
    settings(monkeypatch)
    channel.refresh_channels(Conn(lists=CARD_ROWS))

    assert channel.card_channels() == {"C_OLDFIRE", "G01DBHPLK25"}
    assert "C_OLDFIRE" in channel.case_channels()


def refreshes_recorded(monkeypatch):
    refreshed = []
    monkeypatch.setattr(loop.channel, "refresh_channels", lambda conn: refreshed.append(conn))
    return refreshed


def test_loop_once_refreshes_channels():
    assert "channel.refresh_channels(conn)" in inspect.getsource(loop.once)


def test_app_setting_notify_refreshes_channels(monkeypatch):
    conn = Conn()
    refreshed = refreshes_recorded(monkeypatch)
    watched = {}

    @contextlib.contextmanager
    def fake_session():
        yield conn

    monkeypatch.setattr(loop, "session", fake_session)
    for module in (loop.guards, loop.channelguards, loop.memberguards, loop.automod,
                   loop.responses, loop.screening):
        monkeypatch.setattr(module, "refresh", lambda conn: 0)
    monkeypatch.setattr(loop.purge, "requeue_stranded", lambda conn: [])
    monkeypatch.setattr(loop.loops, "draining", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop.loops, "watching",
                        lambda name, names, on_notify, stopping: watched.update(on_notify=on_notify))
    monkeypatch.setattr(loop.loops, "sweeping", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop, "start_configured_joins", lambda client: None)

    loop.start(SimpleNamespace(client=None), threading.Event())
    refreshed.clear()
    watched["on_notify"](loop.APP_SETTING, "nemo.firehouse_channel")

    assert refreshed == [conn]


def test_a_thread_on_no_case_names_none():
    assert chat.case_of_thread(Conn(), "100.000") is None


def test_the_thread_is_asked_for_by_name_not_by_position():
    conn = Conn({"SELECT case_id FROM (": (6,)})
    assert chat.case_of_thread(conn, "100.000") == 6
    assert conn.args_for("SELECT case_id FROM (")[0] == {"ts": "100.000"}


def test_thread_for_a_case_with_a_report_uses_its_forwarded_ts():
    conn = Conn({"SELECT coalesce(": ("200.000",)})
    assert channel.thread_for(conn, 412) == "200.000"


def test_thread_for_a_case_with_no_thread_at_all_is_none():
    conn = Conn()
    assert channel.thread_for(conn, 412) is None


class Slack:
    def __init__(self, fails=False):
        self.fails = fails
        self.posted = []

    def chat_postMessage(self, **kwargs):
        if self.fails:
            raise RuntimeError("slack said no")
        self.posted.append(kwargs)
        return {"ts": "9.9"}


def test_an_action_echo_quotes_a_report_thread(monkeypatch):
    monkeypatch.setattr(channel.profile, "profile",
        lambda client, user_id: {"name": user_id, "icon": None})
    conn = Conn({
        "r.forwarded_ts FROM": ("100.000",),
        "card_channel_id FROM": ("CCARD",),
    })
    client = Slack()

    ts = channel.post_action_echo(client, conn, 412,
        {"type_key": "warning", "target_user_id": "USUB", "reason": "kept at it"}, "UMOD")

    assert ts == "9.9"
    posted = client.posted[0]
    assert posted["channel"] == "CCARD"
    assert posted["thread_ts"] == "100.000"
    assert posted["blocks"][0]["text"]["text"] == "Warning"
    recorded = conn.args_for("INSERT INTO fd.case_chat")[0]
    assert recorded[0] == 412
    assert recorded[1] == "UMOD"
    assert recorded[2].obj == posted["blocks"]
    assert recorded[3:] == ("CCARD", "9.9", "9.9")


def test_a_channel_ban_echo_names_its_channel_and_end_date(monkeypatch):
    monkeypatch.setattr(channel.profile, "profile",
        lambda client, user_id: {"name": user_id, "icon": None})
    conn = Conn({
        "r.forwarded_ts FROM": ("100.000",),
        "card_channel_id FROM": ("CCARD",),
        "SELECT name FROM raw.channel_dim": ("general",),
    })
    client = Slack()

    channel.post_action_echo(client, conn, 412, {
        "type_key": "channel_ban", "target_user_id": "USUB", "reason": "kept at it",
        "channel_id": "CGEN", "expires_on": "2026-03-10",
    }, "UMOD")

    posted = client.posted[0]
    assert posted["blocks"][0]["text"]["text"] == "Channel ban from #general until 10 Mar"
    assert conn.args_for("SELECT name FROM raw.channel_dim")[0] == ("CGEN",)


def test_an_action_echo_with_nowhere_to_go_posts_nothing(monkeypatch):
    conn = Conn()
    client = Slack()

    assert channel.post_action_echo(client, conn, 412,
        {"type_key": "warning", "target_user_id": "USUB", "reason": "kept at it"}, "UMOD") is None
    assert client.posted == []


def test_an_action_echo_slack_refuses_is_not_recorded(monkeypatch):
    monkeypatch.setattr(channel.profile, "profile",
        lambda client, user_id: {"name": user_id, "icon": None})
    conn = Conn({"r.forwarded_ts FROM": ("100.000",), "card_channel_id FROM": ("CCARD",)})
    client = Slack(fails=True)

    assert channel.post_action_echo(client, conn, 412,
        {"type_key": "warning", "target_user_id": "USUB", "reason": "kept at it"}, "UMOD") is None
    assert conn.args_for("INSERT INTO fd.case_chat") == []


def test_a_resolution_echo_quotes_a_report_thread(monkeypatch):
    monkeypatch.setattr(channel.profile, "profile",
        lambda client, user_id: {"name": user_id, "icon": None})
    conn = Conn({
        "r.forwarded_ts FROM": ("100.000",),
        "card_channel_id FROM": ("CCARD",),
    })
    client = Slack()

    ts = channel.post_resolution_echo(client, conn, 412, "no_action", None, "UMOD")

    assert ts == "9.9"
    posted = client.posted[0]
    assert posted["channel"] == "CCARD"
    assert posted["thread_ts"] == "100.000"
    assert posted["text"] == "No action needed"
    recorded = conn.args_for("INSERT INTO fd.case_chat")[0]
    assert recorded[0] == 412
    assert recorded[1] == "UMOD"
    assert recorded[2].obj == posted["blocks"]
    assert recorded[3:] == ("CCARD", "9.9", "9.9")


def test_a_resolution_echo_with_nowhere_to_go_posts_nothing():
    conn = Conn()
    client = Slack()

    assert channel.post_resolution_echo(client, conn, 412, "no_action", None, "UMOD") is None
    assert client.posted == []


class FetchallConn:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, args=None):
        return self

    def fetchall(self):
        return self.rows


def test_a_follow_up_that_will_not_carry_does_not_block_the_rest(monkeypatch):
    shared_ids = []

    def fake_post_follow_up(client, conn, message_id, channel_id):
        shared_ids.append(message_id)
        if message_id == 46:
            raise RuntimeError("invalid_blocks")
        return "9.9"

    monkeypatch.setattr(channel, "post_follow_up", fake_post_follow_up)
    conn = FetchallConn([(46,), (47,), (48,)])

    assert channel.carry_follow_ups(Slack(), conn, 19) == 2
    assert shared_ids == [46, 47, 48]


def test_a_file_that_will_not_carry_does_not_block_the_rest(monkeypatch):
    shared_ids = []

    def fake_share(client, conn, message_id, channel_id, forwarded_ts, author_fields=None):
        shared_ids.append(message_id)
        if message_id == 46:
            raise RuntimeError("invalid_blocks")
        return "9.9"

    monkeypatch.setattr(channel.attachments, "share", fake_share)
    monkeypatch.setattr(channel, "as_reporter", lambda client, anonymous, reporter: {})
    conn = FetchallConn([
        (46, "100.000", False, "U1", None),
        (47, "100.000", False, "U1", None),
    ])

    assert channel.carry_files(Slack(), conn, 19, "CCARD") == 1
    assert shared_ids == [46, 47]


def report_case(**over):
    case = {"forwarded_ts": None, "report_id": 2, "message_id": 3,
            "is_anonymous": False, "reporter_user_id": "U1"}
    case.update(over)
    return case


def stub_report_views(monkeypatch):
    monkeypatch.setattr(channel.views.report, "build_blocks", lambda case: [])
    monkeypatch.setattr(channel.views.report, "fallback", lambda case: "fallback")
    monkeypatch.setattr(channel.views.report, "metadata", lambda case: {})
    monkeypatch.setattr(channel.attachments, "share", lambda *args, **kwargs: None)


def test_posting_a_report_points_its_message_at_the_new_card(monkeypatch):
    stub_report_views(monkeypatch)
    monkeypatch.setattr(channel, "gather", lambda conn, case_id: report_case())
    conn = Conn()

    ts = channel.post_report(Slack(), conn, 2, "CNEW")

    assert ts == "9.9"
    assert conn.args_for("UPDATE fd.intake_messages")[0] == ("9.9", 3)


def test_rebuilding_a_card_in_a_new_channel_repoints_an_already_mirrored_message(monkeypatch):
    stub_report_views(monkeypatch)
    monkeypatch.setattr(
        channel, "gather", lambda conn, case_id: report_case(mirrored_ts="OLD.TS")
    )
    conn = Conn()

    channel.post_report(Slack(), conn, 2, "CNEW")

    assert conn.args_for("UPDATE fd.intake_messages")[0] == ("9.9", 3)


def test_a_card_sitting_in_a_thread_can_name_its_case():
    assert "card_thread_ts = %(ts)s" in chat.CASE_OF_THREAD


def test_a_report_card_outranks_a_case_card():
    assert chat.CASE_OF_THREAD.index("fd.case_reports") < chat.CASE_OF_THREAD.index(
        "card_thread_ts = %(ts)s"
    )
