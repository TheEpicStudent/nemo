from bot.relay.messages import MessageRelay, shared_at

CHANNEL_ID = "D123"
THREAD = "100.000"


class Slack:
    def __init__(self, info=None, replies=None):
        self.info = info or {}
        self.replies = replies or {}
        self.calls = []

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


def test_the_upload_answer_is_used_when_it_names_the_share():
    slack = Slack()
    one = MessageRelay(slack)
    destination = one.resolve_destination(dict(shared("1.1"), id="F1"), CHANNEL_ID, THREAD)
    assert destination == "1.1"
    assert slack.calls == [], "no need to ask twice when the upload already said"


def test_files_info_is_asked_when_the_upload_says_nothing():
    slack = Slack(info={"file": shared("2.2")})
    destination = MessageRelay(slack).resolve_destination({"id": "F1"}, CHANNEL_ID, THREAD)
    assert destination == "2.2"
    assert slack.calls == ["files.info"]


def test_the_thread_settles_it_when_slack_will_not():
    slack = Slack(replies={"messages": [
        {"ts": "3.0", "files": [{"id": "OTHER"}]},
        {"ts": "3.3", "files": [{"id": "F1"}]},
    ]})
    destination = MessageRelay(slack).resolve_destination({"id": "F1"}, CHANNEL_ID, THREAD)
    assert destination == "3.3", "the message carrying our file is the message it made"
    assert slack.calls == ["files.info", "conversations.replies"]


def test_a_file_nobody_can_place_is_not_guessed_at():
    slack = Slack(replies={"messages": [{"ts": "4.0", "files": [{"id": "OTHER"}]}]})
    assert MessageRelay(slack).resolve_destination({"id": "F1"}, CHANNEL_ID, THREAD) is None


def test_an_upload_with_no_id_is_left_alone():
    slack = Slack()
    assert MessageRelay(slack).resolve_destination({}, CHANNEL_ID, THREAD) is None
    assert slack.calls == []


def test_shared_at_ignores_another_channel():
    assert shared_at({"shares": {"private": {"D999": [{"ts": "9.9"}]}}}, CHANNEL_ID) is None
