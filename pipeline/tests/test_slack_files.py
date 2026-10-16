import contextlib
import io
import urllib.error
import urllib.request

import pytest

from bot.core import blobs, slack_files
from bot.nemo import attachments
from bot.relay import file_notices, intake_files, reply

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
TOKEN = "xoxb-secret"


@pytest.mark.parametrize(("head", "mimetype"), [
    (PNG, "image/png"),
    (b"\xff\xd8\xff\xe0" + b"\x00" * 20, "image/jpeg"),
    (b"GIF89a" + b"\x00" * 20, "image/gif"),
    (b"RIFF\x00\x00\x00\x00WEBPVP8 ", "image/webp"),
    (b"\x00\x00\x00\x18ftypheic" + b"\x00" * 8, "image/heic"),
    (b"\x00\x00\x00\x14ftypqt  " + b"\x00" * 8, "video/quicktime"),
    (b"\x00\x00\x00\x20ftypisom" + b"\x00" * 8, "video/mp4"),
    (b"\x1a\x45\xdf\xa3" + b"\x00" * 20, "video/webm"),
    (b"<svg xmlns='http://www.w3.org/2000/svg'><script/></svg>", None),
    (b"<!doctype html><script>alert(1)</script>", None),
    (b"%PDF-1.7\n", None),
    (b"MZ\x90\x00", None),
    (b"\x00\x00\x00\x20ftypavif" + b"\x00" * 8, None),
    (b"", None),
])
def test_media_type_reads_the_bytes(head, mimetype):
    assert blobs.media_type(head) == mimetype


@pytest.mark.parametrize(("declared", "allowed"), [
    ("image/png", True), ("IMAGE/JPEG; charset=binary", True), ("video/mp4", True),
    ("image/svg+xml", False), ("text/html", False), ("application/pdf", False), (None, False),
])
def test_is_media_type_allows_only_images_and_videos(declared, allowed):
    assert blobs.is_media_type(declared) is allowed


def redirect(from_url, to_url):
    handler = slack_files.SlackOnlyRedirect()
    request = urllib.request.Request(from_url, headers={"Authorization": f"Bearer {TOKEN}"})
    return handler.redirect_request(request, io.BytesIO(), 302, "Found", {}, to_url)


def test_redirect_outside_slack_is_refused():
    with pytest.raises(urllib.error.HTTPError, match="outside Slack"):
        redirect("https://files.slack.com/files-pri/T1-F1/a.png", "https://evil.example/steal")


def test_redirect_to_http_is_refused():
    with pytest.raises(urllib.error.HTTPError):
        redirect("https://files.slack.com/files-pri/T1-F1/a.png", "http://files.slack.com/a.png")


def test_redirect_to_another_slack_host_drops_the_token():
    redirected = redirect("https://files.slack.com/files-pri/T1-F1/a.png", "https://files.slack-edge.com/a.png")

    assert redirected.get_header("Authorization") is None


def test_redirect_on_the_same_host_keeps_the_token():
    redirected = redirect("https://files.slack.com/files-pri/T1-F1/a.png", "https://files.slack.com/files-pri/T1-F1/b.png")

    assert redirected.get_header("Authorization") == f"Bearer {TOKEN}"


def test_redirect_limit_is_small():
    assert slack_files.SlackOnlyRedirect.max_redirections == 3


@pytest.mark.parametrize("url", ["https://evil.example/a.png", "http://files.slack.com/a.png",
                                 "https://files.slack.com.evil.example/a.png", "file:///etc/passwd", None])
def test_download_refuses_urls_outside_slack_without_a_request(monkeypatch, url):
    monkeypatch.setattr(slack_files.OPENER, "open", lambda *args, **kwargs: pytest.fail("no request expected"))

    assert slack_files.download(url, TOKEN, 100) == (None, "refused", blobs.NOT_SLACK_URL)


class FakeResponse:
    def __init__(self, body, content_type="image/png", length=None, status=200):
        self.body = body
        self.status = status
        self.headers = {"Content-Type": content_type, "Content-Length": length}

    def read(self, size):
        return self.body[:size]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


@pytest.mark.parametrize(("response", "state"), [
    (FakeResponse(PNG), "stored"),
    (FakeResponse(b"x" * 200), "too_large"),
    (FakeResponse(PNG, length="999"), "too_large"),
    (FakeResponse(b"<html>login</html>", content_type="text/html"), "refused"),
])
def test_download_reads_slack_files_within_the_limit(monkeypatch, response, state):
    monkeypatch.setattr(slack_files.OPENER, "open", lambda request, timeout: response)

    assert slack_files.download("https://files.slack.com/files-pri/T1-F1/a.png", TOKEN, 100)[1] == state


def test_attachments_fetch_returns_nothing_unless_stored(monkeypatch):
    monkeypatch.setattr(attachments.slack_files, "download", lambda url, token, limit: (None, "refused", "html"))

    assert attachments.fetch("https://files.slack.com/a.png", TOKEN, 100) is None


@pytest.fixture
def drain_calls(monkeypatch):
    calls = {"rows": [], "stored": [], "failed": [], "downloads": []}

    @contextlib.contextmanager
    def fake_session():
        yield None

    monkeypatch.setattr(intake_files, "session", fake_session)
    monkeypatch.setattr(intake_files.blobs, "waiting", lambda conn, limit: calls["rows"])
    monkeypatch.setattr(intake_files.blobs, "store_blob",
                        lambda conn, file_id, body, mimetype: calls["stored"].append((file_id, mimetype)))
    monkeypatch.setattr(intake_files.blobs, "mark_failed",
                        lambda conn, file_id, state, error: calls["failed"].append((file_id, state, error)))
    return calls


def test_drain_refuses_declared_non_media_without_downloading(drain_calls, monkeypatch):
    drain_calls["rows"].append((1, "F1", "https://files.slack.com/a.pdf", 10, "application/pdf"))
    monkeypatch.setattr(intake_files, "download", lambda *args: pytest.fail("no download expected"))

    assert intake_files.drain(TOKEN) == 0
    assert drain_calls["failed"] == [(1, "refused", blobs.NOT_MEDIA)]


def test_drain_stores_the_type_read_from_the_bytes(drain_calls, monkeypatch):
    drain_calls["rows"] += [(1, "F1", "https://files.slack.com/a.jpg", 10, "image/jpeg"),
                            (2, "F2", "https://files.slack.com/b.png", 10, "image/png")]
    bodies = {"https://files.slack.com/a.jpg": PNG, "https://files.slack.com/b.png": b"<html></html>"}
    monkeypatch.setattr(intake_files, "download", lambda url, token, limit: (bodies[url], "stored", None))

    assert intake_files.drain(TOKEN) == 1
    assert drain_calls["stored"] == [(1, "image/png")]
    assert drain_calls["failed"] == [(2, "refused", blobs.NOT_MEDIA)]


@pytest.mark.parametrize(("state", "error", "text"), [
    ("too_large", None, "Not sent: a&amp;b.mp4 (over 25 MiB). Send a smaller file or a link."),
    ("refused", blobs.NOT_MEDIA, "Not sent: a&amp;b.mp4 (only images and videos are accepted)."),
    ("skipped", None, "Not sent: a&amp;b.mp4 (only files uploaded to Slack are accepted)."),
    ("refused", blobs.HTML_BODY, "Not sent: a&amp;b.mp4 (could not be downloaded). Send it again or send a link."),
    ("failed", "timeout", "Not sent: a&amp;b.mp4 (could not be downloaded). Send it again or send a link."),
])
def test_notice_text_names_the_reason(state, error, text):
    assert file_notices.notice_text(state, error, "a&b.mp4") == text


def test_file_label_falls_back_to_file():
    assert reply.file_label(None) == "file"


class NoticeConn:
    def __init__(self, rows, claimed):
        self.rows = rows
        self.claimed = claimed
        self.released = []
        self.sql = None

    def execute(self, sql, args=None):
        self.sql, self.args = sql, args
        if sql == file_notices.RELEASE:
            self.released.append(args[0])
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return (self.args[0],) if self.args[0] in self.claimed else None


class NoticeSlack:
    def __init__(self, failing=False):
        self.failing = failing
        self.posted = []

    def chat_postMessage(self, **kwargs):
        if self.failing:
            raise RuntimeError("ratelimited")
        self.posted.append(kwargs)
        return {"ts": "9.9"}


def notice_setup(monkeypatch, claimed):
    rows = [(1, "D1", "1.0", "too_large", None, "big.mp4"), (2, "D1", "1.0", "refused", blobs.NOT_MEDIA, "a.pdf")]
    conn = NoticeConn(rows, claimed)
    recorded = []

    @contextlib.contextmanager
    def fake_session():
        yield conn

    monkeypatch.setattr(file_notices, "session", fake_session)
    monkeypatch.setattr(file_notices.intake, "record",
                        lambda conn, event, direction: recorded.append((event["subtype"], direction)))
    return conn, recorded


def test_post_notices_tells_the_reporter_once_per_claimed_file(monkeypatch):
    conn, recorded = notice_setup(monkeypatch, claimed={1})
    client = NoticeSlack()

    assert file_notices.post_notices(client) == 1
    assert [(one["channel"], one["thread_ts"]) for one in client.posted] == [("D1", "1.0")]
    assert recorded == [(file_notices.SUBTYPE, "outbound")]


def test_post_notices_releases_the_claim_when_slack_fails(monkeypatch):
    conn, recorded = notice_setup(monkeypatch, claimed={1, 2})

    assert file_notices.post_notices(NoticeSlack(failing=True)) == 0
    assert conn.released == [1, 2]
    assert recorded == []


def test_dropped_files_query_skips_closed_and_unsent_conversations():
    sql = file_notices.DROPPED_FILES
    assert "c.handed_off_at IS NOT NULL AND c.closed_at IS NULL" in sql
    assert "f.reporter_notified_at IS NULL" in sql
    assert "m.direction = 'inbound'" in sql
