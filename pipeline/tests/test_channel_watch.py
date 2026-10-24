from contextlib import contextmanager
from types import SimpleNamespace

from bot.nemo.surface import channel_watch


def capture(monkeypatch):
    recorded = []

    @contextmanager
    def session():
        yield "conn"

    monkeypatch.setattr(channel_watch, "session", session)
    monkeypatch.setattr(channel_watch.channel_dim, "record",
                        lambda conn, channel_id, **fields: recorded.append((channel_id, fields)))
    return recorded


def test_record_channel_renamed_with_name_records_new_name(monkeypatch):
    recorded = capture(monkeypatch)
    ctx = SimpleNamespace(payload={"type": "channel_rename", "channel": {"id": "C1", "name": "lounge"}})

    assert channel_watch.record_channel_renamed(ctx) == "C1"
    assert recorded == [("C1", {"name": "lounge"})]


def test_record_channel_renamed_without_name_returns_none(monkeypatch):
    recorded = capture(monkeypatch)

    assert channel_watch.record_channel_renamed(SimpleNamespace(payload={"channel": {"id": "C1"}})) is None
    assert channel_watch.record_channel_renamed(SimpleNamespace(payload={"channel": "C1"})) is None
    assert recorded == []


class Slack:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)
        return {"ok": True, "ts": f"9.{len(self.posts)}"}


def removal(monkeypatch, wanted=True, archived=False, log_channel="C0LOGS"):
    @contextmanager
    def session():
        yield None

    monkeypatch.setattr(channel_watch, "session", session)
    monkeypatch.setattr(channel_watch.channels, "mode", lambda conn: "on")
    monkeypatch.setattr(channel_watch.channels, "target_channels",
                        lambda client, conn, mode: {"C0GEN"} if wanted else set())
    monkeypatch.setattr(channel_watch.channels, "record_membership", lambda conn, channel_id, inside: None)
    monkeypatch.setattr(channel_watch.channels, "record_join_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(channel_watch.channels, "join", lambda client, conn, channel_id, by=None, verb=None: True)
    monkeypatch.setattr(channel_watch, "fetch_channel_info", lambda client, channel_id: {"archived": archived})
    monkeypatch.setattr(channel_watch.whoami, "bot_user_id", lambda client, name: "UNEMO")
    monkeypatch.setattr(channel_watch.channel, "log_channel", lambda conn: log_channel)
    monkeypatch.setattr(channel_watch, "_removal_threads", {})
    return Slack()


def test_removal_by_a_member_posts_the_firehose_notice(monkeypatch):
    slack = removal(monkeypatch)
    assert channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UMOD") is True
    assert [post["text"] for post in slack.posts] == ["<@UMOD> removed Nemo from <#C0GEN>, attempting to rejoin!"]
    assert slack.posts[0]["channel"] == "C0LOGS"


def test_removal_without_an_actor_posts_nothing(monkeypatch):
    slack = removal(monkeypatch)
    channel_watch.rejoin_if_wanted(slack, "C0GEN")
    assert slack.posts == []


def test_removal_by_nemo_itself_posts_nothing(monkeypatch):
    slack = removal(monkeypatch)
    channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UNEMO")
    assert slack.posts == []


def test_removal_from_an_unwanted_or_archived_channel_posts_nothing(monkeypatch):
    slack = removal(monkeypatch, wanted=False)
    channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UMOD")
    slack_archived = removal(monkeypatch, archived=True)
    channel_watch.rejoin_if_wanted(slack_archived, "C0GEN", by="UMOD")
    assert slack.posts == [] and slack_archived.posts == []


def test_removal_without_a_log_channel_still_rejoins(monkeypatch):
    slack = removal(monkeypatch, log_channel=None)
    assert channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UMOD") is True
    assert slack.posts == []


def test_removals_within_an_hour_go_in_the_thread_of_the_first(monkeypatch):
    slack = removal(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(channel_watch.time, "monotonic", lambda: clock[0])

    channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UMOD")
    clock[0] += 600
    channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UMOD")
    clock[0] += 2000
    channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UOTHER")

    assert [post.get("thread_ts") for post in slack.posts] == [None, "9.1", "9.1"]


def test_a_removal_after_the_hour_starts_a_new_thread(monkeypatch):
    slack = removal(monkeypatch)
    clock = [1000.0]
    monkeypatch.setattr(channel_watch.time, "monotonic", lambda: clock[0])

    channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UMOD")
    clock[0] += 3600
    channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UMOD")
    clock[0] += 60
    channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UMOD")

    assert [post.get("thread_ts") for post in slack.posts] == [None, None, "9.2"]


def test_removals_from_different_channels_keep_their_own_threads(monkeypatch):
    slack = removal(monkeypatch)
    monkeypatch.setattr(channel_watch.channels, "target_channels",
                        lambda client, conn, mode: {"C0GEN", "C0RANDOM"})

    channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UMOD")
    channel_watch.rejoin_if_wanted(slack, "C0RANDOM", by="UMOD")
    channel_watch.rejoin_if_wanted(slack, "C0GEN", by="UMOD")

    assert [post.get("thread_ts") for post in slack.posts] == [None, None, "9.1"]

