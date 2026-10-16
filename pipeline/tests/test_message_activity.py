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


def test_parse_stats_extracts_viewer_reaction_click_and_share_counts():
    stats = activity.parse_stats(STATS)
    assert (stats["viewers"], stats["reacted"], stats["clicked"], stats["shared"]) == (224, 12, 58, 0)
    assert stats["top_reply_ts"] == "1790701348.867479"


def test_parse_stats_clients_are_percent_shares_of_total():
    stats = activity.parse_stats(STATS)
    assert stats["clients"] == [("browser", 123, 55), ("desktop", 75, 33), ("mobile", 26, 12)]


def test_parse_stats_curves_use_utc_timestamps_and_bucket_counts():
    stats = activity.parse_stats(STATS)
    hour = stats["curves"]["1h"]
    assert hour[0] == (dt.datetime(2026, 9, 29, 16, 57, 42, tzinfo=dt.UTC), 0)
    assert hour[1][1] == 3
    assert stats["curves"]["30d"] == [], "a span slack did not send is empty, not missing"


def test_parse_stats_empty_response_returns_zero_counts():
    stats = activity.parse_stats({})
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


def test_may_read_author_returns_true_and_other_user_or_no_author_returns_false():
    assert activity.may_read(USER_ID, USER_ID) is True
    assert activity.may_read(OTHER_USER_ID, USER_ID) is False
    assert activity.may_read(USER_ID, None) is False, "a post with no author is nobody's"


def test_access_may_every_account_capability_skips_role_lookup():
    conn = Conn(rows={"FROM app.capability": ("See how their own post did", "author", True)})
    assert access.may(conn, USER_ID, "message.read") == (True, None)
    assert not any("effective_role" in sql for sql, _ in conn.executed), "no role lookup was needed"


def test_access_may_non_every_account_capability_without_grant_is_denied():
    conn = Conn(rows={"FROM app.capability": ("Read every case", None, False),
                      "holds_capability": (False,)})
    allowed, reason = access.may(conn, USER_ID, "case.read")
    assert allowed is False
    assert reason == "You have no Fire Department access."


def test_build_view_renders_quote_author_channel_stats_and_top_reply_button():
    stats = activity.parse_stats(STATS)
    view = card.build_view(CHANNEL_ID, TS, USER_ID, "hello  world", stats, archived_message=None, channel_members=600)
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


def test_build_view_with_long_text_truncates_quote_to_quote_limit():
    view = card.build_view(CHANNEL_ID, TS, USER_ID, "x" * 1000, activity.parse_stats({}))
    assert len(view["blocks"][0]["text"]["text"]) <= card.QUOTE_LIMIT + 2


def test_replies_line_formats_reply_and_user_counts():
    assert card.replies_line({"reply_count": 8, "reply_users_count": 1}) == "8 from 1 person"
    assert card.replies_line({"reply_count": 0, "reply_users_count": 0}) == "none"


class FakeResponse:
    """Stand-in for the Slack SDK response object: mapping-like, not a dict."""

    def __init__(self, data):
        self.data = data

    def __getitem__(self, key):
        return self.data[key]

    def get(self, key, fallback=None):
        return self.data.get(key, fallback)


class Slack:
    def __init__(self, update_failures=0):
        self.view_opens = []
        self.view_updates = []
        self.ephemeral = []
        self.update_failures = update_failures

    def views_open(self, **kwargs):
        self.view_opens.append(kwargs)
        return FakeResponse({"view": {"id": "V1"}})

    def views_update(self, **kwargs):
        self.view_updates.append(kwargs)
        if self.update_failures > 0:
            self.update_failures -= 1
            raise SlackApiError(
                "invalid_arguments: [ERROR] invalid slack file "
                "[json-pointer:view/blocks/5/slack_file.id/slack_file]",
                FakeResponse({"ok": False, "error": "invalid_arguments"}),
            )
        return FakeResponse({"ok": True})

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


def test_open_activity_modal_thread_reply_sends_not_a_post_without_queries(monkeypatch):
    conn = install_fakes(monkeypatch)
    ctx = shortcut_ctx(thread_ts="1790700000.000001")
    message_activity.open_activity_modal(ctx)
    assert ctx.client.ephemeral[0]["text"] == message_activity.NOT_A_POST
    assert conn.executed == []


def test_open_activity_modal_in_disabled_channel_sends_not_enabled(monkeypatch):
    install_fakes(monkeypatch, enabled=False)
    ctx = shortcut_ctx()
    message_activity.open_activity_modal(ctx)
    assert ctx.client.ephemeral[0]["text"] == message_activity.NOT_ENABLED
    assert ctx.client.view_opens == []


def test_open_activity_modal_for_other_authors_post_sends_not_yours_and_audits(monkeypatch):
    conn = install_fakes(monkeypatch)
    ctx = shortcut_ctx(author=OTHER_USER_ID, user_id=USER_ID)
    message_activity.open_activity_modal(ctx)
    assert ctx.client.ephemeral[0]["text"] == message_activity.NOT_YOURS
    audit_args = [args for sql, args in conn.executed if "fd.audit" in sql]
    assert len(audit_args) == 1
    assert ctx.client.view_opens == []


def test_open_activity_modal_for_author_opens_loading_view_then_updates_with_stats(monkeypatch):
    install_fakes(monkeypatch, stats=activity.parse_stats(STATS), archive_row=(8, 5, None))
    ctx = shortcut_ctx()
    message_activity.open_activity_modal(ctx)
    assert ctx.client.view_opens[0]["view"] == card.loading_view()
    update_call = ctx.client.view_updates[0]
    assert update_call["view_id"] == "V1"
    assert update_call["view"]["title"]["text"] == card.TITLE
    fields = [one["text"] for one in update_call["view"]["blocks"][3]["fields"]]
    assert fields[4] == "*Replies*\n8 from 5 people"


def test_open_activity_modal_with_chart_file_not_ready_retries_view_update(monkeypatch):
    install_fakes(monkeypatch, stats=activity.parse_stats(STATS), archive_row=(8, 5, None))
    monkeypatch.setattr(activity, "chart", lambda *args: ("F1", "1d"))
    ctx = shortcut_ctx()
    ctx.client.update_failures = 1
    monkeypatch.setattr(message_activity.time, "sleep", lambda _: None)

    message_activity.open_activity_modal(ctx)

    assert len(ctx.client.view_updates) == 2, "it waits and puts the same card up again"
    assert ctx.client.view_updates[1]["view"] == ctx.client.view_updates[0]["view"]
    assert any(one["type"] == "image" for one in ctx.client.view_updates[1]["view"]["blocks"])


def test_open_activity_modal_with_chart_file_rejected_at_max_attempts_drops_image(monkeypatch):
    install_fakes(monkeypatch, stats=activity.parse_stats(STATS), archive_row=(8, 5, None))
    monkeypatch.setattr(activity, "chart", lambda *args: ("F1", "1d"))
    ctx = shortcut_ctx()
    ctx.client.update_failures = message_activity.FILE_MAX_ATTEMPTS
    monkeypatch.setattr(message_activity.time, "sleep", lambda _: None)

    message_activity.open_activity_modal(ctx)

    final_view = ctx.client.view_updates[-1]["view"]
    assert not any(one["type"] == "image" for one in final_view["blocks"]), "the chart is dropped"
    assert final_view["title"]["text"] == card.TITLE, "the numbers still fill the modal in"


def test_open_activity_modal_without_stats_shows_error_view(monkeypatch):
    install_fakes(monkeypatch, stats=None)
    ctx = shortcut_ctx()
    message_activity.open_activity_modal(ctx)
    assert ctx.client.view_updates[0]["view"] == card.error_view(message_activity.NOT_NOW)


def test_message_activity_shortcut_is_registered_with_message_read_capability():
    from bot.nemo import app as nemo_app  # noqa: F401  registers every surface

    entries = [one for one in surface.ENTRIES
               if (one.kind, one.key) == (surface.SHORTCUT, message_activity.SHORTCUT)]
    assert entries and entries[0].needs == "message.read"


@pytest.mark.parametrize("key", ["message.read", "message.show"])
def test_capabilities_catalogue_includes_message_capability(key):
    from lib import capabilities

    assert key in capabilities.capabilities()



def test_plot_render_returns_png_with_configured_size():
    import io

    from PIL import Image

    from bot.nemo import plot

    stats = activity.parse_stats(STATS)
    png = plot.render(stats["curves"]["1d"], "1d", viewers=stats["viewers"])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    assert Image.open(io.BytesIO(png)).size == (plot.IMAGE_WIDTH, plot.IMAGE_HEIGHT)


def test_plot_render_with_short_curve_or_unknown_span_returns_none():
    from bot.nemo import plot

    assert plot.render([], "1d") is None
    assert plot.render([(dt.datetime.now(dt.UTC), 3)], "1d") is None
    assert plot.render(activity.parse_stats(STATS)["curves"]["1d"], "2y") is None


def test_plot_span_for_age_returns_matching_span():
    from bot.nemo import plot

    assert plot.span_for(60) == "1h"
    assert plot.span_for(5 * 3600) == "1d"
    assert plot.span_for(3 * 86400) == "1w"
    assert plot.span_for(40 * 86400) == "30d"


class Uploader:
    def __init__(self, response=None, fails=False):
        self.response = response if response is not None else {"files": [{"id": "F1"}]}
        self.fails = fails
        self.uploads = []

    def files_upload_v2(self, **kwargs):
        if self.fails:
            raise RuntimeError("not_allowed")
        self.uploads.append(kwargs)
        return self.response


def test_chart_uploads_png_without_channel_and_returns_file_id():
    stats = activity.parse_stats(STATS)
    client = Uploader()
    posted_at = dt.datetime.now(dt.UTC) - dt.timedelta(hours=5)
    file_id, span = activity.chart(client, stats["curves"], posted_at, stats["viewers"])
    assert (file_id, span) == ("F1", "1d")
    assert client.uploads[0]["filename"] == "activity-1d.png"
    assert "channel" not in client.uploads[0], "the file is not shared anywhere"


def test_chart_with_upload_failure_returns_none_file_id():
    stats = activity.parse_stats(STATS)
    file_id, span = activity.chart(Uploader(fails=True), stats["curves"],
                                   dt.datetime.now(dt.UTC), stats["viewers"])
    assert file_id is None and span == "1h"


def test_build_view_with_chart_and_activity_url_adds_image_and_open_button():
    stats = activity.parse_stats(STATS)
    view = card.build_view(CHANNEL_ID, TS, USER_ID, "hi", stats, chart=("F1", "1d"),
                     activity_url="https://nemo.test/messages/C0ANNOUNCE/1790701062.123456")
    image = next(one for one in view["blocks"] if one["type"] == "image")
    assert image["slack_file"] == {"id": "F1"}
    buttons = next(one for one in view["blocks"] if one["type"] == "actions")["elements"]
    assert buttons[0]["action_id"] == card.OPEN_ACTIVITY
    assert buttons[0]["url"].endswith(f"/messages/{CHANNEL_ID}/{TS}")
