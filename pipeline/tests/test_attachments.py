from bot.core.formatting import quote_text, to_member
from bot.nemo import attachments, channel
from bot.nemo.views import edit, report

CHANNEL_ID = "C1"
THREAD = "100.000"


class Conn:
    def __init__(self, rows):
        self.rows = rows
        self.written = []

    def execute(self, sql, args=None):
        if "SELECT" in sql:
            return self
        self.written.append(args)
        return self

    def fetchall(self):
        return self.rows


class Slack:
    def __init__(self):
        self.uploads = []
        self.posted = []

    def files_upload_v2(self, **kwargs):
        self.uploads.append(kwargs)
        return {"files": [{"id": f"F{len(self.uploads)}"}]}

    def chat_postMessage(self, **kwargs):
        self.posted.append(kwargs)
        return {"ts": "9.9"}


def stub_file_body(monkeypatch, kind):
    monkeypatch.setattr(attachments.blobs, "body_of", lambda conn, sha: (b"bytes", kind))


def test_a_bodyless_report_says_nothing_in_its_place():
    assert quote_text("") == ""
    assert to_member(None) == ""


def test_a_bodyless_report_has_no_empty_quote_to_reject():
    built = report.build_blocks({"case_id": 1, "body": "", "files": [], "shares": []})
    kinds = [block["type"] for block in built]
    assert "rich_text" not in kinds, "an empty quote is invalid blocks"
    assert kinds[0] == "section"


def test_a_picture_goes_up_wearing_the_reporters_face(monkeypatch):
    stub_file_body(monkeypatch, "image/png")
    conn = Conn([(7, "shot.png", "image/png", "abc", 100)])
    slack = Slack()

    ts = attachments.share(slack, conn, 5, CHANNEL_ID, THREAD, author_fields={"username": "Anonymous"})

    assert ts == "9.9"
    assert slack.uploads[0].get("channel") is None, "a blocked file stays private"
    message = slack.posted[0]
    assert message["username"] == "Anonymous"
    assert message["blocks"] == [{
        "type": "image",
        "slack_file": {"id": "F1"},
        "alt_text": "screenshot the reporter sent, shot.png",
    }]
    assert conn.written == [("F1", 5, 7)]


def test_a_picture_gets_a_moment_to_index_before_it_is_referenced(monkeypatch):
    stub_file_body(monkeypatch, "image/png")
    conn = Conn([(7, "shot.png", "image/png", "abc", 100)])
    slack = Slack()
    sleeps = []
    monkeypatch.setattr(attachments.time, "sleep", lambda seconds: sleeps.append(seconds))

    attachments.share(slack, conn, 5, CHANNEL_ID, THREAD, author_fields={"username": "Anonymous"})

    assert sleeps == [attachments.FILE_INDEX_DELAY]


def test_words_with_no_picture_do_not_wait_on_slack_to_index_anything(monkeypatch):
    conn = Conn([])
    slack = Slack()
    sleeps = []
    monkeypatch.setattr(attachments.time, "sleep", lambda seconds: sleeps.append(seconds))

    attachments.share(slack, conn, 5, CHANNEL_ID, THREAD, author_fields={"username": "Anonymous"}, body="look")

    assert sleeps == []


def test_words_and_picture_ride_the_same_message(monkeypatch):
    stub_file_body(monkeypatch, "image/png")
    conn = Conn([(7, "shot.png", "image/png", "abc", 100)])
    slack = Slack()

    attachments.share(slack, conn, 5, CHANNEL_ID, THREAD, author_fields={"username": "Anonymous"}, body="look")

    assert len(slack.posted) == 1, "one message, not a caption and then a picture"
    kinds = [block["type"] for block in slack.posted[0]["blocks"]]
    assert kinds == ["section", "image"]


def test_a_file_slack_will_not_render_is_named_then_uploaded(monkeypatch):
    stub_file_body(monkeypatch, "application/pdf")
    conn = Conn([(7, "notes.pdf", "application/pdf", "abc", None)])
    slack = Slack()

    ts = attachments.share(slack, conn, 5, CHANNEL_ID, THREAD, author_fields={"username": "Anonymous"})

    assert ts == "9.9", "the thread still needs a message to hang the case on"
    assert slack.posted[0]["username"] == "Anonymous"
    assert ":paperclip: notes.pdf" in slack.posted[0]["blocks"][0]["text"]["text"]
    assert slack.uploads[0]["channel"] == CHANNEL_ID, "a file slack cannot block goes up on its own"


def test_nothing_to_carry_posts_nothing(monkeypatch):
    conn = Conn([])
    slack = Slack()

    assert attachments.share(slack, conn, 5, CHANNEL_ID, THREAD, author_fields={"username": "Anonymous"}) is None
    assert slack.posted == []


def test_a_face_slack_cannot_reach_is_not_offered(monkeypatch):
    monkeypatch.delenv("ANONYMOUS_ICON_URL", raising=False)
    monkeypatch.setenv("APP_HOST", "localhost:3000")
    assert channel.anonymous_face() is None, "slack cannot fetch localhost"

    monkeypatch.setenv("APP_HOST", "fire.hackclub.com")
    assert channel.anonymous_face() == "https://fire.hackclub.com/anonymous.png"

    monkeypatch.setenv("ANONYMOUS_ICON_URL", "https://elsewhere.example/a.png")
    assert channel.anonymous_face() == "https://elsewhere.example/a.png"


def test_an_anonymous_reporter_is_worn_like_any_other_face(monkeypatch):
    monkeypatch.setenv("ANONYMOUS_ICON_URL", "https://fire.example/anonymous.png")
    identity = channel.as_reporter(None, True, None)
    assert identity["username"] == "Anonymous"
    assert identity["icon_url"] == "https://fire.example/anonymous.png"


CASE_URL = "https://fire.example/fd/cases/2"


def card(**over):
    case = {"case_id": 2, "body": "he keeps following me", "shares": [],
            "is_anonymous": False, "reporter_user_id": "UALICE", "subjects": ["UBOB"],
            "assignees": [], "category_key": "bullying"}
    case.update(over)
    return report.build_blocks(case)


def test_the_card_is_the_report_and_nothing_else():
    built = card(url=CASE_URL)
    assert [block["type"] for block in built] == ["rich_text"]
    assert built[0]["elements"][0]["type"] == "rich_text_section", "plain text, not a quote"
    assert "Case 2" not in str(built), "the case number lives in the thread"


def test_the_card_holds_only_the_report():
    text = str(card(is_anonymous=False))
    for excluded in ("UALICE", "UBOB", "Bullying", "reported", "overflow"):
        assert excluded not in text


def test_the_thread_header_links_the_case():
    case = {"case_id": 2, "url": CASE_URL}
    assert report.header_blocks(case)[0]["text"]["text"] == f"<{CASE_URL}|Case 2>"
    assert report.header_blocks({"case_id": 2})[0]["text"]["text"] == "Case 2"


def test_a_card_with_nothing_said_names_the_case_instead():
    built = card(body="", blocks=None, url=CASE_URL)
    assert built == report.header_blocks({"case_id": 2, "url": CASE_URL})
    assert not report.needs_header({"case_id": 2, "body": "", "shares": []})


def test_the_quote_keeps_slacks_own_styling_when_it_is_simple():
    blocks = [{"type": "rich_text", "elements": [
        {"type": "rich_text_section", "elements": [
            {"type": "text", "text": "this is "},
            {"type": "text", "text": "urgent", "style": {"bold": True}},
        ]},
    ]}]
    built = card(blocks=blocks)
    quote = next(b for b in built if b["type"] == "rich_text")
    runs = quote["elements"][0]["elements"]
    assert {"type": "text", "text": "urgent", "style": {"bold": True}} in runs


def test_a_list_in_the_report_falls_back_to_plain_text():
    blocks = [{"type": "rich_text", "elements": [
        {"type": "rich_text_list", "style": "bullet", "elements": [
            {"type": "rich_text_section", "elements": [{"type": "text", "text": "one"}]},
        ]},
    ]}]
    built = card(blocks=blocks)
    quote = next(b for b in built if b["type"] == "rich_text")
    assert quote["elements"][0]["elements"] == [
        {"type": "text", "text": "he keeps following me"}
    ]


def test_no_blocks_at_all_still_quotes_the_plain_body():
    built = card(blocks=None)
    quote = next(b for b in built if b["type"] == "rich_text")
    assert quote["elements"][0]["elements"] == [
        {"type": "text", "text": "he keeps following me"}
    ]


def test_the_card_wears_the_reporters_face_but_keeps_its_metadata(monkeypatch):
    monkeypatch.setenv("ANONYMOUS_ICON_URL", "https://fire.example/anonymous.png")
    identity = channel.author_display_fields(None, True, None)
    assert identity == {
        "username": "Anonymous",
        "icon_url": "https://fire.example/anonymous.png",
    }
    assert "metadata" not in identity, "the card's own metadata must survive"


LINK = "https://hackclub.slack.com/archives/C0BNYU3JK3Q/p1786970526885769"


def linked(**over):
    share = {"kind": "unfurl", "source_channel_id": "C0BNYU3JK3Q", "source_channel_name": None,
             "source_ts": "1786970526.885769", "is_reachable": True,
             "source_author_user_id": "U092KBRD5SB", "source_body": "mmm", "permalink": LINK}
    share.update(over)
    return share


def card_with_link(shares):
    return card(body=f"<{LINK}|{LINK}>", shares=shares)


def quotes(built):
    return [b for b in built if b["type"] == "rich_text"]


def test_a_link_slack_never_resolved_is_still_quoted():
    built = card_with_link([linked(is_reachable=False, source_body=None, permalink=None)])

    quote_blocks = quotes(built)
    assert len(quote_blocks) == 1, "the link is all we have, so it stays"
    assert quote_blocks[0]["elements"][0]["elements"][0]["type"] == "link"


class Broken(Slack):
    def files_upload_v2(self, **kwargs):
        raise RuntimeError("slack said no")


def test_an_upload_that_failed_is_not_mistaken_for_nothing_to_carry(monkeypatch):
    stub_file_body(monkeypatch, "image/png")
    conn = Conn([(7, "shot.png", "image/png", "abc", 100)])

    try:
        attachments.share(Broken(), conn, 5, CHANNEL_ID, THREAD, author_fields={"username": "Anonymous"})
    except RuntimeError as failure:
        assert "not settled" in str(failure)
    else:
        raise AssertionError("a failed upload must raise so the message is retried")

    assert conn.written == [], "nothing is marked mirrored when nothing went up"


def test_a_reply_that_is_only_words_lets_slack_unfurl_its_links(monkeypatch):
    conn = Conn([])
    slack = Slack()

    ts = attachments.share(slack, conn, 5, CHANNEL_ID, THREAD,
                     author_fields={"username": "Anonymous"}, body=f"look at {LINK}")

    assert ts == "9.9"
    message = slack.posted[0]
    assert "blocks" not in message, "blocks suppress the unfurl slack would draw"
    assert message["unfurl_links"] is True
    assert message["username"] == "Anonymous"


def test_a_reply_with_a_picture_still_uses_blocks(monkeypatch):
    stub_file_body(monkeypatch, "image/png")
    conn = Conn([(7, "shot.png", "image/png", "abc", 100)])
    slack = Slack()

    attachments.share(slack, conn, 5, CHANNEL_ID, THREAD,
                author_fields={"username": "Anonymous"}, body="look")

    assert [b["type"] for b in slack.posted[0]["blocks"]] == ["section", "image"]


def test_the_card_quotes_no_linked_message_itself():
    built = card(shares=[linked()])
    assert [b["type"] for b in built] == ["rich_text"]
    assert "mmm" not in str(built), "linked messages go in the thread, not on the card"


def test_the_card_menu_never_outgrows_the_three_dot_menu():
    for case in ({"case_id": 19, "assignees": []}, {"case_id": 19, "assignees": ["UME"]},
                 {"case_id": 19, "resolved_at": "2026-10-10"}):
        assert len(edit.menu(case)["options"]) <= 5


def test_more_holds_what_the_card_menu_has_no_room_for():
    labels = [label for label, _ in edit.more_options(True, None, [{"id": 1}])]
    assert labels == ["People", "Set the violation", "Reverse an action", "Merge"]
    assert [label for label, _ in edit.more_options(False, "spam", [])] == ["People"]


def test_every_more_button_carries_the_case_it_acts_on():
    built = edit.more_view(19, edit.more_options(True, None, []))
    buttons = built["blocks"][-1]["elements"]
    assert len({one["action_id"] for one in buttons}) == len(buttons), "slack wants them unique"
    assert all(one["action_id"].startswith(edit.MORE_ACTION) for one in buttons)
    assert [edit.parse_menu_value(one["value"])[1] for one in buttons] == [19] * len(buttons)


def test_every_card_menu_option_carries_the_case_it_acts_on():
    case = {"case_id": 19, "category_key": None, "live_actions": 1,
            "assignees": ["UME"], "resolved_at": None}

    for one in edit.menu(case)["options"]:
        verb, case_id = edit.parse_menu_value(one["value"])
        assert case_id == 19
        assert verb


class FakeConn:
    def __init__(self, ts=None):
        self.ts = ts
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append(" ".join(sql.split())[:60])
        return self

    def fetchone(self):
        return (self.ts,)


def test_the_card_row_is_claimed_before_slack_is_asked():
    assert "FOR UPDATE" in channel.CLAIM_CARD, "two threads must not both post a card"
    assert "forwarded_ts" in channel.CLAIM_CARD
