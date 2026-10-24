from types import SimpleNamespace

from bot.relay.messages import MessageRelay, file_share_ts

CHANNEL_ID = "D123"
THREAD_TS = "100.000"


class Slack:
    def __init__(self, info=None, replies=None):
        self.info = info or {}
        self.replies = replies or {}
        self.calls = []
        self.posted = []

    def chat_postMessage(self, **kwargs):
        self.calls.append("chat.postMessage")
        self.posted.append(kwargs)
        return {"ts": "2.2"}

    def files_info(self, file):
        self.calls.append("files.info")
        if not self.info:
            raise RuntimeError("no_file_info")
        return self.info

    def conversations_replies(self, channel, ts, limit):
        self.calls.append("conversations.replies")
        return self.replies


def shared(ts):
    return {"shares": {"private": {CHANNEL_ID: [{"ts": ts}]}}}


def test_resolve_file_ts_upload_with_share_returns_ts_without_api_calls():
    slack = Slack()
    relay = MessageRelay(slack)
    destination = relay.resolve_file_ts(dict(shared("1.1"), id="F1"), CHANNEL_ID, THREAD_TS)
    assert destination == "1.1"
    assert slack.calls == [], "no need to ask twice when the upload already said"


def test_resolve_file_ts_upload_without_share_uses_files_info():
    slack = Slack(info={"file": shared("2.2")})
    destination = MessageRelay(slack).resolve_file_ts({"id": "F1"}, CHANNEL_ID, THREAD_TS)
    assert destination == "2.2"
    assert slack.calls == ["files.info"]


def test_resolve_file_ts_without_files_info_uses_thread_replies():
    slack = Slack(replies={"messages": [
        {"ts": "3.0", "files": [{"id": "OTHER"}]},
        {"ts": "3.3", "files": [{"id": "F1"}]},
    ]})
    destination = MessageRelay(slack).resolve_file_ts({"id": "F1"}, CHANNEL_ID, THREAD_TS)
    assert destination == "3.3", "the message carrying our file is the message it made"
    assert slack.calls == ["files.info", "conversations.replies"]


def test_resolve_file_ts_unmatched_file_returns_none():
    slack = Slack(replies={"messages": [{"ts": "4.0", "files": [{"id": "OTHER"}]}]})
    assert MessageRelay(slack).resolve_file_ts({"id": "F1"}, CHANNEL_ID, THREAD_TS) is None


def test_resolve_file_ts_without_file_id_returns_none_and_makes_no_calls():
    slack = Slack()
    assert MessageRelay(slack).resolve_file_ts({}, CHANNEL_ID, THREAD_TS) is None
    assert slack.calls == []


def test_file_share_ts_other_channel_returns_none():
    assert file_share_ts({"shares": {"private": {"D999": [{"ts": "9.9"}]}}}, CHANNEL_ID) is None


def test_post_message_sends_reply_with_link_previews():
    slack = Slack()
    queued = SimpleNamespace(body="see https://hackclub.slack.com/archives/C1/p1792814195112529",
                             mode="body", requested_by="UFIRE", channel_id=CHANNEL_ID,
                             thread_ts=THREAD_TS)

    assert MessageRelay(slack).post_message(queued) == "2.2"
    assert slack.posted[0]["unfurl_links"] is True and slack.posted[0]["unfurl_media"] is True
