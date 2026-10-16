import contextlib
import datetime as dt

import pytest

from bot.core.formatting import short_end
from bot.nemo import channelguards, guards, userbots
from bot.nemo.enforcement import slowmode
from bot.nemo.surface import thread_slowmode
from bot.nemo.views import slowmode as card

CHANNEL_ID = "C1"
THREAD = "1700000000.000000"
TS = "1700000000.000100"
USER_ID = "U1"
MOD = "UMOD"
NOW = dt.datetime(2026, 10, 16, 9, 30, tzinfo=dt.UTC)
END = dt.datetime(2026, 10, 17, 14, 30, tzinfo=dt.UTC)


def current(**over):
    row = {"id": 9, "seconds": 30, "expires_at": END, "reason": "Heated argument",
           "opened_by": MOD, "exempt": ["UEXEMPT"]}
    row.update(over)
    return row


def submission(**over):
    row = {"starting": True, "duration": "1h", "extend": None, "until": None, "seconds": "30",
           "reason": "Heated argument", "exempt": []}
    row.update(over)
    return row


def block_ids(view):
    return [block.get("block_id") for block in view["blocks"]]


def test_build_view_new_has_optional_duration_without_default():
    view = card.build_view(CHANNEL_ID, THREAD)
    duration = view["blocks"][0]["element"]

    assert block_ids(view) == [card.DURATION, card.SECONDS, card.REASON, card.EXEMPT]
    assert view["submit"]["text"] == "Enable"
    assert view["blocks"][0]["optional"] is True
    assert duration["placeholder"]["text"] == "No end"
    assert "initial_option" not in duration
    assert [one["value"] for one in duration["options"]] == [*card.DURATIONS, card.CUSTOM]


def test_build_view_custom_adds_until_block():
    assert block_ids(card.build_view(CHANNEL_ID, THREAD, custom=True))[:2] == [card.DURATION, card.UNTIL]


def test_build_view_existing_shows_remaining_time_and_extend_block():
    view = card.build_view(CHANNEL_ID, THREAD, current(), now=NOW)

    assert block_ids(view)[1:] == [card.EXTEND, card.SECONDS, card.REASON, card.EXEMPT]
    assert view["submit"]["text"] == "Save"
    assert view["blocks"][0]["text"]["text"] == \
        f"*Enabled* · ends in 1d 5h · {short_end(END)} · set by <@{MOD}>"
    assert view["blocks"][0]["accessory"]["action_id"] == card.DISABLE
    assert view["blocks"][3]["element"]["initial_value"] == "Heated argument"
    assert view["blocks"][4]["element"]["initial_users"] == ["UEXEMPT"]


def test_submitted_values_custom_duration_returns_until_and_fields():
    state = {"values": {
        card.DURATION: {card.DURATION: {"selected_option": {"value": card.CUSTOM}}},
        card.UNTIL: {card.UNTIL: {"selected_date_time": int(END.timestamp())}},
        card.SECONDS: {card.SECONDS: {"value": "45"}},
        card.REASON: {card.REASON: {"value": "  Heated argument "}},
        card.EXEMPT: {card.EXEMPT: {"selected_users": ["UEXEMPT"]}},
    }}

    assert card.submitted_values(state) == {
        "starting": True, "duration": card.CUSTOM, "extend": None, "until": END, "seconds": "45",
        "reason": "Heated argument", "exempt": ["UEXEMPT"]}


def test_submitted_values_existing_view_is_not_starting():
    state = {"values": {card.EXTEND: {card.EXTEND: {"selected_option": None}}}}

    assert card.submitted_values(state)["starting"] is False


@pytest.mark.parametrize(("over", "errors"), [
    ({}, None),
    ({"duration": None}, None),
    ({"duration": card.CUSTOM}, {card.UNTIL: "Select the end."}),
    ({"duration": card.CUSTOM, "until": NOW - dt.timedelta(minutes=1)},
     {card.UNTIL: "Select a time in the future."}),
    ({"seconds": "0"}, {card.SECONDS: "Enter 1 to 3600 seconds."}),
    ({"seconds": "3601"}, {card.SECONDS: "Enter 1 to 3600 seconds."}),
    ({"seconds": "fast"}, {card.SECONDS: "Enter 1 to 3600 seconds."}),
    ({"reason": ""}, {card.REASON: "Add a reason."}),
    ({"starting": False, "duration": None}, None),
])
def test_validation_errors_invalid_field_returns_block_error(over, errors):
    assert card.validation_errors(submission(**over), NOW) == errors


@pytest.mark.parametrize(("over", "row", "expected"), [
    ({}, None, NOW + dt.timedelta(hours=1)),
    ({"duration": None}, None, None),
    ({"duration": None}, current(), None),
    ({"duration": card.CUSTOM, "until": END}, None, END),
    ({"starting": False, "extend": "1h"}, current(), END + dt.timedelta(hours=1)),
    ({"starting": False}, current(), END),
    ({"starting": False, "extend": "30m"}, current(expires_at=None), NOW + dt.timedelta(minutes=30)),
])
def test_new_end_returns_start_or_extended_end(over, row, expected):
    assert card.new_end(submission(**over), row, NOW) == expected


def test_notice_includes_cooldown_end_and_actor():
    posted = card.notice(30, END, MOD)

    assert posted["text"] == f"*Slow mode enabled* · 30s cooldown · ends {short_end(END)}"
    assert posted["blocks"][1]["elements"][0]["text"] == f"Fire Department · <@{MOD}>"


def test_confirmation_without_end_returns_no_end_date_text():
    assert card.confirmation("enabled", 120, None, "Heated argument") == \
        "Slow mode enabled · 2m cooldown · no end date · Reason: Heated argument"


def test_removal_notice_in_thread_quotes_reply():
    notice = card.removal_notice(12, "my reply", in_thread=True)

    assert notice["text"] == "*Slow mode* · next reply in 12s"
    assert notice["blocks"][1]["elements"][0]["elements"][0]["text"] == "my reply"


def test_removal_notice_empty_body_has_no_quote_block():
    assert len(card.removal_notice(12, "", in_thread=False)["blocks"]) == 1


@pytest.fixture
def cache(monkeypatch):
    monkeypatch.setattr(channelguards, "_guards", {})
    monkeypatch.setattr(channelguards, "_loaded", True)
    monkeypatch.setattr(userbots, "_users", {})
    return channelguards._guards


def live(cache, thread_ts, guard_id, seconds, allowed=(), expires_at=None, threads=False):
    settings = {"seconds": seconds, **({"threads": True} if threads else {})}
    cache[(channelguards.SLOWMODE, CHANNEL_ID, thread_ts)] = channelguards.LiveGuard(
        guard_id, settings, frozenset(allowed), expires_at)


def test_thread_slowmode_lookup_is_separate_from_channel_active_guard(cache):
    live(cache, THREAD, 9, 30)

    assert channelguards.thread_slowmode(CHANNEL_ID, THREAD).guard_id == 9
    assert channelguards.active_guard(CHANNEL_ID, channelguards.SLOWMODE) is None
    assert channelguards.is_guarded(CHANNEL_ID) is True


def test_thread_slowmode_past_expiry_returns_none(cache):
    live(cache, THREAD, 9, 30, expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1))

    assert channelguards.thread_slowmode(CHANNEL_ID, THREAD) is None


def test_refresh_keys_guards_by_channel_and_thread(cache):
    rows = [("slowmode", CHANNEL_ID, "", 1, {"seconds": 60}, None, []),
            ("slowmode", CHANNEL_ID, THREAD, 2, {"seconds": 30}, END, ["UEXEMPT"])]

    class Conn:
        def execute(self, sql, args=None):
            return self

        def fetchall(self):
            return rows

    channelguards.refresh(Conn())

    assert set(channelguards._guards) == {("slowmode", CHANNEL_ID, ""), ("slowmode", CHANNEL_ID, THREAD)}
    assert channelguards._guards[("slowmode", CHANNEL_ID, THREAD)].expires_at == END


class Conn:
    def __init__(self, remaining=12):
        self.remaining = remaining
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        sql = self.executed[-1][0]
        if "INSERT INTO fd.slowmode_clock" in sql:
            return None
        if "FROM fd.slowmode_clock" in sql:
            return (self.remaining,)
        if "holds_capability" in sql:
            return (False,)
        return (1,)

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class Slack:
    def __init__(self):
        self.ephemeral = []

    def chat_postEphemeral(self, **kwargs):
        self.ephemeral.append(kwargs)


class EventCtx:
    def __init__(self, event):
        self.payload = event
        self.client = Slack()


def reply(**over):
    return {"user": USER_ID, "channel": CHANNEL_ID, "ts": TS, "thread_ts": THREAD, "text": "my reply", **over}


@contextlib.contextmanager
def session_of(conn):
    yield conn


@pytest.fixture
def enforcing(monkeypatch, cache):
    conn = Conn()
    removed = []
    monkeypatch.setattr(slowmode, "session", lambda: session_of(conn))
    monkeypatch.setattr(slowmode.guard_actions, "remove",
                        lambda client, channel_id, ts: removed.append(ts) or True)
    monkeypatch.setattr(guards, "has_live_guard", lambda channel_id, thread_ts: False)
    return conn, removed


def test_on_message_thread_slowmode_fast_reply_is_removed_and_notified(enforcing, cache):
    conn, removed = enforcing
    live(cache, THREAD, 9, 30)
    ctx = EventCtx(reply())

    assert slowmode.on_message(ctx) is True
    assert removed == [TS]
    assert conn.args_for("INSERT INTO fd.slowmode_clock")[0][1] == THREAD
    assert conn.args_for("INSERT INTO fd.channel_guard_events")[0][0] == 9
    assert ctx.client.ephemeral[0]["text"] == "*Slow mode* · next reply in 12s"


def test_on_message_thread_slowmode_overrides_channel_slowmode(enforcing, cache):
    conn, _removed = enforcing
    live(cache, "", 1, 600, threads=True)
    live(cache, THREAD, 9, 30)

    slowmode.on_message(EventCtx(reply()))

    assert conn.args_for("INSERT INTO fd.slowmode_clock")[0][3] == 30
    assert conn.args_for("INSERT INTO fd.channel_guard_events")[0][0] == 9


def test_on_message_thread_slowmode_channel_message_returns_none(enforcing, cache):
    _conn, removed = enforcing
    live(cache, THREAD, 9, 30)

    assert slowmode.on_message(EventCtx(reply(thread_ts=None))) is None
    assert removed == []


def test_on_message_thread_slowmode_locked_thread_returns_none(enforcing, cache, monkeypatch):
    _conn, removed = enforcing
    live(cache, THREAD, 9, 30)
    monkeypatch.setattr(guards, "has_live_guard", lambda channel_id, thread_ts: True)

    assert slowmode.on_message(EventCtx(reply())) is None
    assert removed == []


def test_on_message_thread_slowmode_exempt_member_returns_none(enforcing, cache):
    _conn, removed = enforcing
    live(cache, THREAD, 9, 30, allowed=[USER_ID])

    assert slowmode.on_message(EventCtx(reply())) is None
    assert removed == []


class Client:
    def __init__(self, fails=False):
        self.fails = fails
        self.posted = []
        self.updated = []
        self.opened = []

    def chat_postMessage(self, **kwargs):
        if self.fails:
            raise RuntimeError("not_in_channel")
        self.posted.append(kwargs)

    def views_update(self, **kwargs):
        self.updated.append(kwargs)

    def views_open(self, **kwargs):
        self.opened.append(kwargs)


class SurfaceCtx:
    def __init__(self, view, client=None):
        self.view = view
        self.client = client or Client()
        self.user_id = MOD
        self.channel_id = CHANNEL_ID
        self.thread_ts = THREAD
        self.trigger_id = "T1"
        self.ack_calls = []
        self.ephemerals = []

    def ack(self, **kwargs):
        self.ack_calls.append(kwargs)

    def join(self, channel_id=None):
        return None

    def post_ephemeral(self, message, channel_id=None, thread_ts=None):
        self.ephemerals.append(message)

    def post_ephemeral_or_dm(self, message, channel_id=None, thread_ts=None):
        self.ephemerals.append(message)


def submitted_view(seconds="30", reason="Heated argument", duration="1h", extend=None):
    duration_state = {card.EXTEND: {card.EXTEND: {"selected_option": extend and {"value": extend}}}} \
        if duration is None else \
        {card.DURATION: {card.DURATION: {"selected_option": {"value": duration}}}}
    return {
        "id": "V1", "hash": "H1", "callback_id": card.CALLBACK,
        "private_metadata": card.metadata(CHANNEL_ID, THREAD),
        "state": {"values": {
            **duration_state,
            card.SECONDS: {card.SECONDS: {"value": seconds}},
            card.REASON: {card.REASON: {"value": reason}},
            card.EXEMPT: {card.EXEMPT: {"selected_users": ["UEXEMPT"]}},
        }},
    }


@pytest.fixture
def guard_calls(monkeypatch):
    calls = {"opened": [], "updates": [], "allows": [], "lifted": [], "row": None}
    monkeypatch.setattr(thread_slowmode, "session", lambda: session_of(object()))
    monkeypatch.setattr(channelguards, "slowmode_row", lambda conn, channel_id, thread_ts: calls["row"])
    monkeypatch.setattr(channelguards, "open_slowmode",
                        lambda conn, *args: calls["opened"].append(args) or 9)
    monkeypatch.setattr(channelguards, "update_slowmode",
                        lambda conn, row, *args: calls["updates"].append(args) or row["id"])
    monkeypatch.setattr(channelguards, "set_allows",
                        lambda conn, guard_id, ids, by: calls["allows"].append((guard_id, ids)))
    monkeypatch.setattr(channelguards, "lift", lambda conn, guard_id, by: calls["lifted"].append(guard_id) or CHANNEL_ID)
    monkeypatch.setattr(channelguards, "refresh", lambda conn: 0)
    return calls


def test_submit_slowmode_new_opens_guard_and_confirms(guard_calls):
    ctx = SurfaceCtx(submitted_view())
    before = dt.datetime.now(dt.UTC)

    assert thread_slowmode.submit_slowmode(ctx) == 9
    (channel_id, thread_ts, seconds, by, reason, ends), = guard_calls["opened"]
    assert (channel_id, thread_ts, seconds, by, reason) == (CHANNEL_ID, THREAD, 30, MOD, "Heated argument")
    assert before + dt.timedelta(hours=1) <= ends <= dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)
    assert guard_calls["allows"] == [(9, ["UEXEMPT"])]
    assert ctx.client.posted[0]["text"] == f"*Slow mode enabled* · 30s cooldown · ends {short_end(ends)}"
    assert ctx.ephemerals == [f"Slow mode enabled · 30s cooldown · ends {short_end(ends)} · Reason: Heated argument"]


def test_submit_slowmode_existing_extends_without_notice(guard_calls):
    guard_calls["row"] = current()
    ctx = SurfaceCtx(submitted_view(seconds="60", duration=None, extend="2h"))

    thread_slowmode.submit_slowmode(ctx)

    assert guard_calls["updates"] == [(60, MOD, "Heated argument", END + dt.timedelta(hours=2))]
    assert ctx.client.posted == []
    assert ctx.ephemerals == [f"Slow mode updated · 1m cooldown · ends {short_end(END + dt.timedelta(hours=2))} "
                        "· Reason: Heated argument"]


def test_submit_slowmode_ended_guard_returns_none_with_message(guard_calls):
    ctx = SurfaceCtx(submitted_view(duration=None, extend="1h"))

    assert thread_slowmode.submit_slowmode(ctx) is None
    assert guard_calls["opened"] == []
    assert ctx.ephemerals == ["Slow mode already ended"]


def test_submit_slowmode_notice_failure_lifts_guard(guard_calls):
    ctx = SurfaceCtx(submitted_view(), Client(fails=True))

    assert thread_slowmode.submit_slowmode(ctx) is None
    assert guard_calls["lifted"] == [9]
    assert ctx.ephemerals == ["Slow mode not enabled · Nemo could not post in this thread (RuntimeError)"]


def test_submit_slowmode_invalid_cooldown_acks_errors(guard_calls):
    ctx = SurfaceCtx(submitted_view(seconds="0"))

    thread_slowmode.submit_slowmode(ctx)

    assert ctx.ack_calls == [{"response_action": "errors", "errors": {card.SECONDS: "Enter 1 to 3600 seconds."}}]
    assert guard_calls["opened"] == []


def test_disable_slowmode_lifts_guard_and_updates_view(guard_calls):
    guard_calls["row"] = current()
    ctx = SurfaceCtx(submitted_view())

    assert thread_slowmode.disable_slowmode(ctx) == 9
    assert guard_calls["lifted"] == [9]
    assert ctx.client.updated[0]["view"]["callback_id"] == card.DISABLED_CALLBACK
    assert ctx.ephemerals == ["Slow mode disabled"]


def test_open_slowmode_modal_existing_guard_shows_save_button(guard_calls):
    guard_calls["row"] = current()
    ctx = SurfaceCtx({})

    thread_slowmode.open_slowmode_modal(ctx)

    assert ctx.client.opened[0]["view"]["submit"]["text"] == "Save"


class NoticeConn:
    def __init__(self, claimed):
        self.claimed = claimed
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return self.claimed

    def args_for(self, sql):
        return [args for one, args in self.executed if one == sql]


class Poster:
    def __init__(self, fails=False):
        self.fails = fails
        self.posted = []

    def chat_postMessage(self, **kwargs):
        if self.fails:
            raise RuntimeError("not_in_channel")
        self.posted.append(kwargs)
        return {"ts": "1700000000.000900"}


def claimed_notice(attempts=1, thread_ts=""):
    return (5, CHANNEL_ID, thread_ts, {"seconds": 30}, None, MOD, attempts)


def test_post_notices_posts_in_channel_and_records_ts(monkeypatch):
    conn = NoticeConn([claimed_notice()])
    monkeypatch.setattr(slowmode, "session", lambda: session_of(conn))
    client = Poster()

    assert slowmode.post_notices(client) == 1
    assert client.posted[0]["channel"] == CHANNEL_ID
    assert client.posted[0]["thread_ts"] is None
    assert client.posted[0]["text"] == "*Slow mode enabled* · 30s cooldown · no end date"
    assert conn.args_for(slowmode.NOTICE_POSTED) == [("1700000000.000900", 5)]


@pytest.mark.parametrize(("attempts", "again"), [(1, True), (2, True), (3, False)])
def test_post_notices_failure_requeues_below_three_attempts(monkeypatch, attempts, again):
    conn = NoticeConn([claimed_notice(attempts=attempts)])
    monkeypatch.setattr(slowmode, "session", lambda: session_of(conn))

    assert slowmode.post_notices(Poster(fails=True)) == 0
    assert bool(conn.args_for(slowmode.NOTICE_AGAIN)) is again
    assert conn.args_for(slowmode.NOTICE_POSTED) == []


def test_claim_notices_selects_live_guards_with_notice_wanted():
    assert "WHERE notice_wanted AND state = 'live'" in slowmode.CLAIM_NOTICES
    assert "FOR UPDATE SKIP LOCKED" in slowmode.CLAIM_NOTICES


@pytest.mark.parametrize(("duration", "has_end"), [(card.CUSTOM, True), ("1h", False)])
def test_reshape_slowmode_on_duration_shows_until_only_for_custom(guard_calls, duration, has_end):
    ctx = SurfaceCtx(submitted_view(duration=duration))

    thread_slowmode.reshape_slowmode_on_duration(ctx)

    assert (card.UNTIL in block_ids(ctx.client.updated[0]["view"])) is has_end
