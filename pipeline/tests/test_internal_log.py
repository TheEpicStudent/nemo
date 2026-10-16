import contextlib
import datetime as dt
import threading
from types import SimpleNamespace

import pytest

from bot.core.formatting import short_end
from bot.nemo import guard_actions, internal_log, loop
from bot.nemo.views.activity import message_url

END = dt.datetime(2026, 10, 17, 14, 30, tzinfo=dt.UTC)
THREAD = "1700000000.000100"
THREAD_LINK = f"<{message_url('C1', THREAD)}|thread>"


def entry(verb, actor="UMOD", before=None, after=None, entity_type="member_guard"):
    return {"id": 1, "actor": actor, "entity_type": entity_type, "entity_id": 7, "verb": verb,
            "before": before, "after": after}


SHUSH = ("shush", "U1", None, "spam", END, None)
BAN = ("channel_ban", "U1", "C1", "spam", None, None)


@pytest.mark.parametrize(("row", "made", "line"), [
    (SHUSH, entry("opened"), f"Shush · <@U1> · ends {short_end(END)} · Reason: spam · by <@UMOD>"),
    (BAN, entry("opened"), "Channel ban · <@U1> · <#C1> · no end date · Reason: spam · by <@UMOD>"),
    (SHUSH, entry("extended"), f"Shush extended · <@U1> · ends {short_end(END)} · by <@UMOD>"),
    (SHUSH, entry("lifted", after={"lift_reason": "appeal upheld"}),
     "Shush lifted · <@U1> · Reason: appeal upheld · by <@UMOD>"),
    (BAN, entry("lifted", actor="nemo", after={"lift_reason": internal_log.LAPSED_BECAUSE}),
     "Channel ban ended · <@U1> · <#C1>"),
    (SHUSH, entry("attached"), None),
])
def test_member_line_reads_each_guard_change(row, made, line):
    assert internal_log.member_line(made, row) == line


SLOW = ("slowmode", "C1", "", {"seconds": 30, "threads": True}, "Heated", END)
THREAD_SLOW = ("slowmode", "C1", THREAD, {"seconds": 120}, "Heated", None)
GATE = ("account_age", "C1", "", {"min_age_days": 7}, None, None)


@pytest.mark.parametrize(("row", "made", "line"), [
    (SLOW, entry("opened", entity_type="channel_guard"),
     f"Slow mode enabled · <#C1> · 30s cooldown · ends {short_end(END)} · threads · Reason: Heated · by <@UMOD>"),
    (THREAD_SLOW, entry("opened", entity_type="channel_guard"),
     f"Slow mode enabled · <#C1> · {THREAD_LINK} · 2m cooldown · no end date · Reason: Heated · by <@UMOD>"),
    (GATE, entry("opened", entity_type="channel_guard"), "New-account gate enabled · <#C1> · 7 days · by <@UMOD>"),
    (SLOW, entry("extended", entity_type="channel_guard"),
     f"Slow mode extended · <#C1> · ends {short_end(END)} · by <@UMOD>"),
    (SLOW, entry("lifted", entity_type="channel_guard"), "Slow mode disabled · <#C1> · by <@UMOD>"),
    (SLOW, entry("lifted", actor="system", entity_type="channel_guard"), "Slow mode ended · <#C1>"),
])
def test_channel_line_reads_each_guard_change(row, made, line):
    assert internal_log.channel_line(made, row) == line


def test_allow_line_names_the_member_and_the_guard():
    added = entry("added", after={"subject_id": "U2"}, entity_type="channel_allow")
    removed = entry("removed", before={"subject_id": "B1"}, entity_type="channel_allow")
    bots = ("bot_allowlist", "C1", "", {}, None, None)

    assert internal_log.allow_line(added, SLOW) == "Exemption added · <@U2> · Slow mode · <#C1> · by <@UMOD>"
    assert internal_log.allow_line(removed, bots) == "Bot removed from allow list · <@B1> · <#C1> · by <@UMOD>"


LOCK = ("lock", "C1", THREAD, "raid", END, "running", None)


@pytest.mark.parametrize(("row", "made", "line"), [
    (LOCK, entry("opened", entity_type="thread_guard"),
     f"Thread locked · <#C1> · {THREAD_LINK} · ends {short_end(END)} · Reason: raid · by <@UMOD>"),
    (LOCK, entry("extended", entity_type="thread_guard"),
     f"Lock extended · <#C1> · {THREAD_LINK} · ends {short_end(END)} · by <@UMOD>"),
    (LOCK[:5] + ("done", None), entry("lifted", entity_type="thread_guard"),
     f"Thread unlocked · <#C1> · {THREAD_LINK} · by <@UMOD>"),
    (LOCK[:5] + ("done", None), entry("lifted", actor="system", entity_type="thread_guard"),
     f"Lock ended · <#C1> · {THREAD_LINK}"),
    (LOCK[:5] + ("done", internal_log.REPLACED_BY_DESTROY), entry("lifted", entity_type="thread_guard"), None),
    (LOCK[:5] + ("failed", "warning not posted"), entry("lifted", actor="system", entity_type="thread_guard"), None),
    (("destroy",) + LOCK[1:], entry("opened", entity_type="thread_guard"), None),
])
def test_thread_line_logs_locks_and_leaves_destroys_to_their_notice(row, made, line):
    assert internal_log.thread_line(made, row) == line


def test_automod_line_links_and_quotes_the_message():
    match = (3, "badword", "U1", "C1", "https://hackclub.slack.com/archives/C1/p1", "a badword here")

    assert internal_log.automod_line(match) == \
        'Automod · "badword" · <@U1> · <#C1> · <https://hackclub.slack.com/archives/C1/p1|message>\n> a badword here'


class Conn:
    def __init__(self, entries=(), matches=(), rows=None):
        self.entries = list(entries)
        self.matches = list(matches)
        self.rows = rows or {}
        self.moved = []
        self.sql = None

    def execute(self, sql, args=None):
        self.sql, self.args = sql, args
        if sql == internal_log.MOVE_CURSOR:
            self.moved.append(args)
        return self

    def fetchone(self):
        if self.sql == internal_log.CURSOR:
            return (10,)
        return self.rows.get(self.sql)

    def fetchall(self):
        return self.entries if self.sql == internal_log.AUDIT_AFTER else self.matches


class Slack:
    def __init__(self, fails_on=None):
        self.fails_on = fails_on
        self.posted = []

    def chat_postMessage(self, **kwargs):
        if self.fails_on and self.fails_on in kwargs["text"]:
            raise RuntimeError("ratelimited")
        self.posted.append(kwargs)


def drain_with(monkeypatch, conn, client, log_channel="CLOGS"):
    @contextlib.contextmanager
    def session_of():
        yield conn

    monkeypatch.setattr(internal_log, "session", session_of)
    monkeypatch.setattr(internal_log.channel, "log_channel", lambda conn=None: log_channel)
    return internal_log.drain(client)


AUDIT_ROWS = [(11, "UMOD", "member_guard", 7, "opened", None, None),
              (12, "UMOD", "member_guard", 7, "attached", None, None)]


def test_drain_posts_lines_and_moves_the_cursor(monkeypatch):
    conn = Conn(AUDIT_ROWS, [(4, "badword", "U1", "C1", None, "")], rows={internal_log.MEMBER_GUARD: SHUSH})
    client = Slack()

    assert drain_with(monkeypatch, conn, client) == 3
    assert [one["text"].split(" · ")[0] for one in client.posted] == ["Shush", 'Automod']
    assert all(one["channel"] == "CLOGS" for one in client.posted)
    assert conn.moved == [(11, "audit"), (12, "audit"), (4, "automod")]


def test_drain_stops_at_a_line_that_will_not_post(monkeypatch):
    conn = Conn(AUDIT_ROWS[:1], rows={internal_log.MEMBER_GUARD: SHUSH})

    assert drain_with(monkeypatch, conn, Slack(fails_on="Shush")) == 0
    assert conn.moved == []


def test_drain_without_a_log_channel_moves_on_quietly(monkeypatch):
    conn = Conn(AUDIT_ROWS[:1], rows={internal_log.MEMBER_GUARD: SHUSH})
    client = Slack()

    assert drain_with(monkeypatch, conn, client, log_channel=None) == 1
    assert client.posted == []
    assert conn.moved == [(11, "audit")]


def test_audit_query_is_bounded_and_filtered():
    assert "occurred_at > now() - interval '7 days'" in internal_log.AUDIT_AFTER
    assert "entity_type = ANY(%s) AND verb = ANY(%s)" in internal_log.AUDIT_AFTER


@pytest.fixture
def notify(monkeypatch):
    woken = []

    @contextlib.contextmanager
    def session_of():
        yield object()

    watched = {}
    monkeypatch.setattr(loop, "session", session_of)
    for module in (loop.guards, loop.channelguards, loop.memberguards, loop.automod,
                   loop.responses, loop.screening):
        monkeypatch.setattr(module, "refresh", lambda conn: 0)
    monkeypatch.setattr(loop.channel, "refresh_channels", lambda conn: None)
    monkeypatch.setattr(loop.purge, "requeue_stranded", lambda conn: [])
    monkeypatch.setattr(loop.loops, "draining", lambda name, *args, **kwargs: (lambda: woken.append(name)))
    monkeypatch.setattr(loop.loops, "timed", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop.loops, "sweeping", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop.loops, "watching", lambda name, names, on_notify, stopping:
                        watched.update(names=names, on_notify=on_notify))
    loop.start(SimpleNamespace(client=None), threading.Event())
    return watched, woken


@pytest.mark.parametrize(("channel_name", "payload", "wakes"), [
    (loop.AUDIT_EVENT, '{"source": "fire_engine", "actions": ["opened"]}', True),
    (loop.AUDIT_EVENT, '{"source": "slack", "actions": ["user_login"]}', False),
    (loop.AUTOMOD_MATCH, "", True),
])
def test_notifications_wake_the_internal_log(notify, channel_name, payload, wakes):
    watched, woken = notify

    watched["on_notify"](channel_name, payload)

    assert loop.AUDIT_EVENT in watched["names"] and loop.AUTOMOD_MATCH in watched["names"]
    assert ("nemo-log" in woken) is wakes


def test_destroy_notice_counts_the_messages(monkeypatch):
    posted = []
    monkeypatch.setattr(guard_actions.channel, "log_channel", lambda conn=None: "CLOGS")
    monkeypatch.setattr(guard_actions, "archive_url", lambda channel_id, thread_ts: "https://fe/archive")
    client = SimpleNamespace(chat_postMessage=lambda **kwargs: posted.append(kwargs))

    guard_actions.post_destroy_notice(client, object(), "C1", THREAD, "UMOD", 42)

    assert posted[0]["text"] == "Thread destroyed · <#C1> · 42 messages · by <@UMOD> · <https://fe/archive|archive>"


def test_bot_kick_notification_wakes_the_kick_drain(notify):
    watched, woken = notify

    watched["on_notify"](loop.BOT_KICK, "B1")

    assert loop.BOT_KICK in watched["names"]
    assert "nemo-kicks" in woken
