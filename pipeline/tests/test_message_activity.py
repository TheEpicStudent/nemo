import datetime as dt

import pytest
from slack_sdk.errors import SlackApiError

from bot.core import access
from bot.nemo import activity, surface
from bot.nemo.views import activity as card
from bot.nemo.surface import message_activity

CHANNEL_ID = "C0ANNOUNCE"
TS = "1790701062.123456"
USER_ID = "U0ME"
OTHER_USER_ID = "U0THEM"

STATS = {
    "num_users_viewed": 224,
    "num_users_clicked": 58,
    "num_users_reacted": 12,
    "num_shares": 0,
    "top_threaded_reply_by_reactions_ts": "1790701348.867479",
    "viewers_time_series": {
        "data": [
            {"seriesType": "1h", "series": [
                {"value": 1790701062000000, "count": 0},
                {"value": 1790701122000000, "count": 3},
            ]},
            {"seriesType": "1d", "series": [
                {"value": 1790701062000000, "count": 0},
                {"value": 1790701962000000, "count": 23},
                {"value": 1790702862000000, "count": 14},
            ]},
        ]
    },
    "client_breakdown": {"desktop_count": 75, "browser_count": 123, "mobile_count": 26},
}


def test_the_numbers_are_lifted_off_the_answer():
    stats = activity.shaped(STATS)
    assert (stats["viewers"], stats["reacted"], stats["clicked"], stats["shared"]) == (224, 12, 58, 0)
    assert stats["top_reply_ts"] == "1790701348.867479"


def test_the_client_split_is_shares_of_the_whole():
    stats = activity.shaped(STATS)
    assert stats["clients"] == [("browser", 123, 55), ("desktop", 75, 33), ("mobile", 26, 12)]


def test_a_curve_is_utc_stamps_and_new_viewers_per_bucket():
    stats = activity.shaped(STATS)
    hour = stats["curves"]["1h"]
    assert hour[0] == (dt.datetime(2026, 9, 29, 16, 57, 42, tzinfo=dt.UTC), 0)
    assert hour[1][1] == 3
    assert stats["curves"]["30d"] == [], "a span slack did not send is empty, not missing"


def test_an_empty_answer_shapes_to_zeros():
    stats = activity.shaped({})
    assert stats["viewers"] == 0
    assert stats["clients"] == [("browser", 0, None), ("desktop", 0, None), ("mobile", 0, None)]


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

    def fetchall(self):
        return []


def test_only_the_author_reads_their_post():
    assert activity.may_read(USER_ID, USER_ID) is True
    assert activity.may_read(OTHER_USER_ID, USER_ID) is False
    assert activity.may_read(USER_ID, None) is False, "a post with no author is nobody's"


def test_an_every_account_capability_needs_no_fire_department_grant():
    conn = Conn(rows={"FROM app.capability": ("See how their own post did", "author", True)})
    assert access.may(conn, USER_ID, "message.read") == (True, None)
    assert not any("effective_role" in sql for sql, _ in conn.executed), "no role lookup was needed"


def test_a_capability_that_is_not_every_account_still_needs_access():
    conn = Conn(rows={"FROM app.capability": ("Read every case", None, False),
                      "holds_capability": (False,)})
    allowed, reason = access.may(conn, USER_ID, "case.read")
    assert allowed is False
    assert reason == "You have no Fire Department access."


def test_the_card_quotes_the_post_and_says_who_where_when():
    stats = activity.shaped(STATS)
    view = card.build_view(CHANNEL_ID, TS, USER_ID, "hello  world", stats, archived_message=None, crowd=600)
    blocks = view["blocks"]
    assert blocks[0]["text"]["text"] == "> hello world"
    assert f"<@{USER_ID}>" in blocks[1]["elements"][0]["text"]
    assert f"<#{CHANNEL_ID}>" in blocks[1]["elements"][0]["text"]
    fields = [one["text"] for one in blocks[3]["fields"]]
    assert fields[0] == "*Viewers*\n224 · 37% of the channel"
    assert fields[4] == "*Replies*\nnot available yet"
    assert blocks[4]["elements"][0]["text"] == "55% browser · 33% desktop · 12% mobile"
    assert blocks[5]["elements"][0]["text"] == "3 viewers in the first hour, 37 in the first day"
    buttons = next(one for one in blocks if one["type"] == "actions")["elements"]
    assert [one["action_id"] for one in buttons] == [card.OPEN_TOP_REPLY]
    assert buttons[0]["url"] == (
        "https://hackclub.slack.com/archives/C0ANNOUNCE/p1790701348867479"
        "?thread_ts=1790701062.123456&cid=C0ANNOUNCE"
    )


def test_a_long_post_is_cut_short_in_the_card():
    view = card.build_view(CHANNEL_ID, TS, USER_ID, "x" * 1000, activity.shaped({}))
    assert len(view["blocks"][0]["text"]["text"]) <= card.QUOTE_LIMIT + 2


def test_replies_read_off_the_archive_row():
    assert card.replies_line({"reply_count": 8, "reply_users_count": 1}) == "8 from 1 person"
    assert card.replies_line({"reply_count": 0, "reply_users_count": 0}) == "none"


class Answer:
    """Stand-in for the Slack SDK response object: mapping-like, not a dict."""

    def __init__(self, data):
        self.data = data

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, fallback=None):
        return self.data.get(key, fallback)


class Slack:
    def __init__(self, update_failures=0):
        self.opened = []
        self.updated = []
        self.ephemeral = []
        self.update_failures = update_failures

    def views_open(self, **kwargs):
        self.opened.append(kwargs)
        return Answer({"view": {"id": "V1"}})

    def views_update(self, **kwargs):
        self.updated.append(kwargs)
        if self.update_failures > 0:
            self.update_failures -= 1
            raise SlackApiError(
                "invalid_arguments: [ERROR] invalid slack file "
                "[json-pointer:view/blocks/5/slack_file.id/slack_file]",
                Answer({"ok": False, "error": "invalid_arguments"}),
            )
        return Answer({"ok": True})

    def chat_postEphemeral(self, **kwargs):
        self.ephemeral.append(kwargs)


class _Session:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, *_):
        return False


def shortcut_ctx(author=USER_ID, user_id=USER_ID, thread_ts=None):
    message = {"ts": TS, "user": author, "text": "big news"}
    if thread_ts:
        message["thread_ts"] = thread_ts
    body = {"user": {"id": user_id}, "channel": {"id": CHANNEL_ID}, "trigger_id": "T1", "message": message}
    entry = surface.SurfaceEntry(surface.SHORTCUT, message_activity.SHORTCUT, "message.read", None)
    return surface.Ctx(entry, body, Slack(), lambda: None)


def install_fakes(monkeypatch, enabled=True, stats=None, archive_row=None):
    rows = {}
    if enabled:
        rows["app.channel_message_activity"] = (1,)
    if archive_row:
        rows["FROM archive.message"] = archive_row
    conn = Conn(rows=rows)
    monkeypatch.setattr(message_activity, "session", lambda: _Session(conn))
    monkeypatch.setattr(activity, "fetch", lambda channel_id, ts: stats)
    return conn


def test_a_reply_is_turned_away_before_anything_is_read(monkeypatch):
    conn = install_fakes(monkeypatch)
    ctx = shortcut_ctx(thread_ts="1790700000.000001")
    message_activity.open_activity_modal(ctx)
    assert ctx.client.ephemeral[0]["text"] == message_activity.NOT_A_POST
    assert conn.executed == []


def test_a_channel_that_is_not_shown_says_so(monkeypatch):
    install_fakes(monkeypatch, enabled=False)
    ctx = shortcut_ctx()
    message_activity.open_activity_modal(ctx)
    assert ctx.client.ephemeral[0]["text"] == message_activity.NOT_ENABLED
    assert ctx.client.opened == []


def test_somebody_elses_post_is_refused_and_written_down(monkeypatch):
    conn = install_fakes(monkeypatch)
    ctx = shortcut_ctx(author=OTHER_USER_ID, user_id=USER_ID)
    message_activity.open_activity_modal(ctx)
    assert ctx.client.ephemeral[0]["text"] == message_activity.NOT_YOURS
    refusals = [args for sql, args in conn.executed if "fd.audit" in sql]
    assert len(refusals) == 1
    assert ctx.client.opened == []


def test_the_author_gets_a_modal_that_fills_in_once_slack_answers(monkeypatch):
    install_fakes(monkeypatch, stats=activity.shaped(STATS), archive_row=(8, 5, None))
    ctx = shortcut_ctx()
    message_activity.open_activity_modal(ctx)
    assert ctx.client.opened[0]["view"] == card.loading_view()
    update = ctx.client.updated[0]
    assert update["view_id"] == "V1"
    assert update["view"]["title"]["text"] == card.TITLE
    fields = [one["text"] for one in update["view"]["blocks"][3]["fields"]]
    assert fields[4] == "*Replies*\n8 from 5 people"


def test_a_chart_slack_has_not_finished_taking_is_tried_again(monkeypatch):
    install_fakes(monkeypatch, stats=activity.shaped(STATS), archive_row=(8, 5, None))
    monkeypatch.setattr(activity, "chart", lambda *args: ("F1", "1d"))
    ctx = shortcut_ctx()
    ctx.client.update_failures = 1
    monkeypatch.setattr(message_activity.time, "sleep", lambda _: None)

    message_activity.open_activity_modal(ctx)

    assert len(ctx.client.updated) == 2, "it waits and puts the same card up again"
    assert ctx.client.updated[1]["view"] == ctx.client.updated[0]["view"]
    assert any(one["type"] == "image" for one in ctx.client.updated[1]["view"]["blocks"])


def test_a_chart_slack_keeps_refusing_leaves_the_numbers_standing(monkeypatch):
    install_fakes(monkeypatch, stats=activity.shaped(STATS), archive_row=(8, 5, None))
    monkeypatch.setattr(activity, "chart", lambda *args: ("F1", "1d"))
    ctx = shortcut_ctx()
    ctx.client.update_failures = message_activity.FILE_TRIES
    monkeypatch.setattr(message_activity.time, "sleep", lambda _: None)

    message_activity.open_activity_modal(ctx)

    last = ctx.client.updated[-1]["view"]
    assert not any(one["type"] == "image" for one in last["blocks"]), "the chart is dropped"
    assert last["title"]["text"] == card.TITLE, "the numbers still fill the modal in"


def test_when_slack_will_not_answer_the_modal_says_so(monkeypatch):
    install_fakes(monkeypatch, stats=None)
    ctx = shortcut_ctx()
    message_activity.open_activity_modal(ctx)
    assert ctx.client.updated[0]["view"] == card.error_view(message_activity.NOT_NOW)


def test_the_shortcut_is_registered_behind_message_read():
    from bot.nemo import app as nemo_app  # noqa: F401  registers every surface

    entries = [one for one in surface.ENTRIES
               if (one.kind, one.key) == (surface.SHORTCUT, message_activity.SHORTCUT)]
    assert entries and entries[0].needs == "message.read"


@pytest.mark.parametrize("key", ["message.read", "message.show"])
def test_the_new_capabilities_are_in_the_catalogue(key):
    from lib import capabilities

    assert key in capabilities.capabilities()



def test_a_curve_renders_to_a_png_of_the_right_size():
    import io

    from PIL import Image

    from bot.nemo import plot

    stats = activity.shaped(STATS)
    png = plot.render(stats["curves"]["1d"], "1d", viewers=stats["viewers"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(io.BytesIO(png)).size == (plot.WIDE, plot.HIGH)


def test_a_curve_too_short_to_draw_is_none():
    from bot.nemo import plot

    assert plot.render([], "1d") is None
    assert plot.render([(dt.datetime.now(dt.UTC), 3)], "1d") is None
    assert plot.render(activity.shaped(STATS)["curves"]["1d"], "2y") is None


def test_the_span_follows_the_age_of_the_post():
    from bot.nemo import plot

    assert plot.span_for(60) == "1h"
    assert plot.span_for(5 * 3600) == "1d"
    assert plot.span_for(3 * 86400) == "1w"
    assert plot.span_for(40 * 86400) == "30d"


class Uploader:
    def __init__(self, answer=None, fails=False):
        self.answer = answer if answer is not None else {"files": [{"id": "F1"}]}
        self.fails = fails
        self.uploads = []

    def files_upload_v2(self, **kwargs):
        if self.fails:
            raise RuntimeError("not_allowed")
        self.uploads.append(kwargs)
        return self.answer


def test_the_chart_goes_to_slack_privately_and_comes_back_as_a_file_id():
    stats = activity.shaped(STATS)
    client = Uploader()
    posted = dt.datetime.now(dt.UTC) - dt.timedelta(hours=5)
    file_id, span = activity.chart(client, stats["curves"], posted, stats["viewers"])
    assert (file_id, span) == ("F1", "1d")
    assert client.uploads[0]["filename"] == "activity-1d.png"
    assert "channel" not in client.uploads[0], "the file is not shared anywhere"


def test_a_chart_slack_will_not_take_is_simply_left_out():
    stats = activity.shaped(STATS)
    file_id, span = activity.chart(Uploader(fails=True), stats["curves"],
                                   dt.datetime.now(dt.UTC), stats["viewers"])
    assert file_id is None and span == "1h"


def test_the_card_carries_the_chart_and_the_way_to_the_page():
    stats = activity.shaped(STATS)
    view = card.build_view(CHANNEL_ID, TS, USER_ID, "hi", stats, chart=("F1", "1d"),
                     activity_url="https://nemo.test/messages/C0ANNOUNCE/1790701062.123456")
    image = next(one for one in view["blocks"] if one["type"] == "image")
    assert image["slack_file"] == {"id": "F1"}
    buttons = next(one for one in view["blocks"] if one["type"] == "actions")["elements"]
    assert buttons[0]["action_id"] == card.OPEN_ACTIVITY
    assert buttons[0]["url"].endswith(f"/messages/{CHANNEL_ID}/{TS}")
