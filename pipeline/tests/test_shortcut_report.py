import pytest

from bot.nemo import channel
from bot.nemo.views import report, shortcut_report

PERMALINK = "https://hackclub.slack.com/archives/C0CONSTRUCT/p1792379645000100"


def share(**over):
    built = {"kind": "forward", "source_channel_id": "C0CONSTRUCT", "permalink": PERMALINK,
             "source_author_user_id": "U0KABOOM", "raw": {"author_kind": "member"}}
    built.update(over)
    return built


def shortcut_case(**over):
    built = {"case_id": 4913, "entry_point": "shortcut", "body": "mmm", "blocks": None,
             "shares": [share()], "subjects": ["U0KABOOM"]}
    built.update(over)
    return built


QUOTE = {"type": "rich_text", "elements": [{"type": "rich_text_quote", "elements": [{"type": "text", "text": "mmm"}]}]}


def test_blocks_quote_the_message_and_name_author_channel_and_link():
    assert shortcut_report.blocks(shortcut_case()) == [
        QUOTE,
        {"type": "context", "elements": [{
            "type": "mrkdwn",
            "text": f"<@U0KABOOM> in <#C0CONSTRUCT> · <{PERMALINK}|View message>"}]},
    ]


@pytest.mark.parametrize(("source", "line"), [
    (share(source_author_user_id=None, raw={"author_kind": "bot"}), f"Bot in <#C0CONSTRUCT> · <{PERMALINK}|View message>"),
    (share(source_author_user_id=None, raw={"author_kind": "withheld"}), f"<#C0CONSTRUCT> · <{PERMALINK}|View message>"),
    (share(permalink=None), "<@U0KABOOM> in <#C0CONSTRUCT>"),
    (share(source_channel_id=None), f"<@U0KABOOM> · <{PERMALINK}|View message>"),
])
def test_source_line_per_author_kind(source, line):
    assert shortcut_report.source_line(source) == line


def test_quote_prefers_rich_text_blocks_of_the_message():
    section = {"type": "rich_text_section", "elements": [{"type": "text", "text": "hello", "style": {"bold": True}}]}
    built = shortcut_report.quote(shortcut_case(blocks=[{"type": "rich_text", "elements": [section]}]))

    assert built["elements"][0] == {"type": "rich_text_quote", "elements": section["elements"]}


def test_report_blocks_for_shortcut_case_use_the_shortcut_layout_and_need_a_header():
    case = shortcut_case()

    assert report.build_blocks(case) == shortcut_report.blocks(case)
    assert report.needs_header(case) is True


def test_report_blocks_for_dm_case_are_unchanged():
    case = {"case_id": 1, "entry_point": "dm", "body": "they did a thing", "shares": [], "subjects": []}

    assert report.build_blocks(case) == [report.body(case)]
    assert shortcut_report.is_shortcut(case) is False


def test_unfurl_for_shortcut_report_posts_nothing(monkeypatch):
    class Conn:
        def execute(self, sql, args=None):
            self.sql = sql
            return self

        def fetchone(self):
            return ("shortcut",) if self.sql == channel.ENTRY_POINT_OF_MESSAGE else None

    class Slack:
        def chat_postMessage(self, **kwargs):
            raise AssertionError("posted")

    assert channel.unfurl(Slack(), Conn(), 41, "C0FIREHOUSE", "1.0") is None
