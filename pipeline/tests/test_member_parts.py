from types import SimpleNamespace

import pytest

from bot.core import formatting
from bot.relay import messages


def test_split_text_keeps_short_text_whole():
    assert formatting.split_text("hello there", limit=50) == ["hello there"]


def test_split_text_prefers_paragraphs_then_lines_then_words():
    paragraphs = "a" * 30 + "\n\n" + "b" * 30
    lines = "a" * 30 + "\n" + "b" * 30
    words = "a" * 30 + " " + "b" * 30

    assert formatting.split_text(paragraphs, limit=40) == ["a" * 30, "b" * 30]
    assert formatting.split_text(lines, limit=40) == ["a" * 30, "b" * 30]
    assert formatting.split_text(words, limit=40) == ["a" * 30, "b" * 30]


def test_split_text_cuts_hard_without_spaces():
    assert formatting.split_text("x" * 95, limit=40) == ["x" * 40, "x" * 40, "x" * 15]


def test_split_text_never_breaks_a_slack_link():
    link = "<https://example.com/x|the thread>"
    text = "w" * 30 + " " + link + " " + "z" * 30

    assert formatting.split_text(text, limit=60) == ["w" * 30, link, "z" * 30]


def test_member_parts_escapes_each_part_but_keeps_links():
    parts = formatting.member_parts("1 < 2 & <https://example.com|link>")

    assert parts == ["1 &lt; 2 &amp; <https://example.com|link>"]
    assert formatting.member_parts("   ") == []


class FakeSlack:
    def __init__(self, failing_at=None):
        self.failing_at = failing_at
        self.posted = []

    def chat_postMessage(self, **kwargs):
        if len(self.posted) == self.failing_at:
            raise RuntimeError("ratelimited")
        self.posted.append(kwargs)
        return {"ts": f"1.{len(self.posted)}"}


def queued(body):
    return SimpleNamespace(id=9, body=body, channel_id="D1", thread_ts="1.0", mode="body", requested_by=None)


@pytest.fixture
def long_body():
    return "\n\n".join(f"paragraph {index} " + "word " * 500 for index in range(3))


def test_post_message_sends_every_part_in_order(long_body):
    relay = messages.MessageRelay()
    relay.client = FakeSlack()

    assert relay.post_message(queued(long_body)) == "1.1"
    texts = [one["text"] for one in relay.client.posted]
    assert len(texts) == 3
    assert [text.split(" ")[1] for text in texts] == ["0", "1", "2"]
    assert all(len(text) <= formatting.MEMBER_PART_LIMIT for text in texts)
    assert all(one["thread_ts"] == "1.0" for one in relay.client.posted)


def test_post_message_keeps_the_first_ts_when_a_later_part_fails(long_body):
    relay = messages.MessageRelay()
    relay.client = FakeSlack(failing_at=1)

    assert relay.post_message(queued(long_body)) == "1.1"


def test_post_message_raises_when_the_first_part_fails(long_body):
    relay = messages.MessageRelay()
    relay.client = FakeSlack(failing_at=0)

    with pytest.raises(RuntimeError):
        relay.post_message(queued(long_body))
