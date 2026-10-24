from datetime import datetime, timedelta, timezone

from bot.nemo import channel, chat, command
from bot.nemo.views import linked, report

LINK = "https://hackclub.slack.com/archives/C0BNYU3JK3Q/p1786970526885769"
OTHER = "https://hackclub.slack.com/archives/C0LOUNGE00/p1786970600000100"
CHANNEL_ID = "C_FIRE"
CARD = "100.000"
HANDED_OFF_AT = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def at(minutes):
    return HANDED_OFF_AT + timedelta(minutes=minutes)


def share(**overrides):
    share_row = {"kind": "unfurl", "source_channel_id": "C0BNYU3JK3Q", "source_channel_name": None,
                 "source_ts": "1786970526.885769", "is_reachable": True,
                 "source_author_user_id": "UDRACULA", "source_body": "mwah", "permalink": LINK}
    share_row.update(overrides)
    return share_row


def forward(**overrides):
    return share(kind="forward", source_channel_id="C0FWD0000", source_ts="1786970700.000200",
                 permalink=None, **overrides)


def runs(block):
    return block["elements"][0]["elements"]


def numbers_in(block):
    return [run["text"] for run in runs(block) if run["type"] == "text" and "(" in run["text"]]


def card(body, blocks=None, shares=()):
    case = {"case_id": 23, "body": body, "blocks": blocks, "shares": list(shares),
            "subjects": [], "assignees": [], "category_key": None,
            "numbering": linked.numbering(body, list(shares), 1)}
    return report.build_blocks(case)


def test_build_blocks_repeated_link_numbers_each_occurrence():
    built = card(f"test <{LINK}> test <{LINK}> test meow")
    assert numbers_in(built[0]) == [" (1)", " (2)"]


def test_build_blocks_number_follows_link_run():
    built = card(f"test <{LINK}> test")
    kinds = [(run["type"], run.get("text")) for run in runs(built[0])]
    assert kinds == [("text", "test "), ("link", None), ("text", " (1)"), ("text", " test")]


def mention():
    return {"type": "message_mention", "url": LINK, "text": LINK, "author_id": "UDRACULA",
            "channel_id": "C0BNYU3JK3Q", "message_ts": "1786970526.885769"}


def test_build_blocks_rich_text_mention_and_link_are_numbered():
    blocks = [{"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [
        {"type": "text", "text": "test "},
        mention(),
        {"type": "text", "text": " test "},
        {"type": "link", "url": LINK},
    ]}]}]
    built = card(f"test <{LINK}|{LINK}> test <{LINK}>", blocks=blocks)
    assert numbers_in(built[0]) == [" (1)", " (2)"]


def test_numbering_self_labelled_links_match_share_without_double_count():
    text = f"test <{LINK}|{LINK}> test <{LINK}|{LINK}> test <{LINK}|{LINK}>"
    numbered = linked.numbering(text, [share()], 1)

    assert linked.size(numbered) == 3
    assert [one["url"] for one in numbered["links"]] == [LINK] * 3
    assert linked.numbered_text(f"<{LINK}|{LINK}>", linked.numbering(f"<{LINK}|{LINK}>", [], 7)) \
        == f"<{LINK}|{LINK}> (7)"


def test_build_blocks_non_slack_link_is_not_numbered():
    built = card("see <https://example.com>")
    assert numbers_in(built[0]) == []


def test_numbered_text_with_start_offset_continues_numbering():
    text = f"also <{OTHER}>"
    assert linked.numbered_text(text, linked.numbering(text, [], 3)) == f"also <{OTHER}> (3)"


def test_numbering_forward_share_gets_number_after_links():
    text = f"look <{LINK}>"
    numbered = linked.numbering(text, [share(), forward()], 1)
    assert linked.numbered_text(text, numbered) == f"look <{LINK}> (1)\nforwarded (2)"


def test_numbering_forward_of_linked_message_counts_once():
    numbered = linked.numbering(f"look <{LINK}>", [share(kind="forward")], 1)
    assert linked.size(numbered) == 1


def test_build_blocks_forward_only_report_renders_forwarded_run():
    built = card("", shares=[forward()])
    assert [run["text"] for run in runs(built[0])] == ["forwarded (1)"]


def test_reply_blocks_link_items_render_number_quote_and_author():
    text = f"test <{LINK}> test <{LINK}>"
    items = linked.items(linked.numbering(text, [share()], 1), [share()])
    blocks = linked.reply_blocks(items)

    assert [b["type"] for b in blocks] == ["rich_text", "context"] * 2
    head, quote_block = blocks[0]["elements"]
    assert head["elements"] == [{"type": "link", "url": LINK}, {"type": "text", "text": " (1)"}]
    assert quote_block["type"] == "rich_text_quote"
    assert quote_block["elements"] == [{"type": "text", "text": "mwah"}]
    assert blocks[1]["elements"][0]["text"] == "<@UDRACULA> in <#C0BNYU3JK3Q>"
    assert blocks[2]["elements"][0]["elements"][1]["text"] == " (2)"


def test_reply_blocks_unreachable_link_renders_not_accessible_context():
    text = f"look <{LINK}>"
    unreachable = share(kind="link", is_reachable=False, source_body=None, permalink=None)
    blocks = linked.reply_blocks(linked.items(linked.numbering(text, [unreachable], 1), [unreachable]))

    assert len(blocks[0]["elements"]) == 1, "no empty quote"
    assert blocks[1]["elements"][0]["text"] == "Message not accessible"


def test_reply_blocks_over_block_limit_truncates_with_more_line():
    text = " ".join(f"<{LINK}>" for _ in range(30))
    blocks = linked.reply_blocks(linked.items(linked.numbering(text, [share()], 1), [share()]))

    assert len(blocks) <= 50
    assert blocks[-1]["elements"][0]["text"] == "6 more in Fire Engine"


class Conn:
    def __init__(self, answers):
        self.answers = answers
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        for mark, rows in self.answers.items():
            if mark in self.executed[-1][0]:
                return rows
        return []

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class Slack:
    def __init__(self, messages=()):
        self.messages = list(messages)
        self.calls = []
        self.posted = []
        self.updated = []

    def conversations_join(self, **kwargs):
        self.calls.append(("join", kwargs["channel"]))
        return {"ok": True}

    def conversations_history(self, **kwargs):
        self.calls.append(("history", kwargs["channel"]))
        return {"messages": self.messages}

    def chat_postMessage(self, **kwargs):
        self.calls.append(("post", kwargs["channel"]))
        self.posted.append(kwargs)
        return {"ts": "9.9"}

    def chat_update(self, **kwargs):
        self.updated.append(kwargs)
        return {"ok": True}


def conversation(*rows, shares=()):
    return {
        "c.handed_off_at": [(*row, HANDED_OFF_AT) for row in rows],
        "s.message_id, s.kind": list(shares),
    }


def test_message_numbering_continues_across_messages_and_skips_deleted():
    conn = Conn(conversation(
        (1, f"<{LINK}> and <{LINK}>", at(-5), CARD, None),
        (2, f"before it went up <{OTHER}>", at(-1), None, None),
        (3, f"later <{OTHER}>", at(1), "3.3", None),
        (4, f"gone <{OTHER}>", at(2), None, at(3)),
        (5, f"and <{LINK}>", at(4), None, None),
    ))

    numbers = channel.message_numbering(conn, 7)

    assert sorted(numbers) == [1, 2, 3, 5]
    assert [numbers[one]["start"] for one in (1, 2, 3, 5)] == [1, 3, 4, 5]


def unfurl_setup(state, *rows):
    answers = conversation(*rows)
    answers["unfurl_digest, unfurled_at"] = [state]
    answers["s.raw"] = [tuple(share().get(key) for key in (
        "kind", "source_channel_id", "source_channel_name", "source_ts", "permalink",
        "is_reachable", "source_author_user_id", "source_body")) + (None,)]
    return Conn(answers)


def test_unfurl_posts_reply_in_card_thread_and_stores_ts():
    conn, slack = unfurl_setup((7, None, None, None), (1, f"<{LINK}>", at(-5), CARD, None)), Slack()

    assert channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD) == "9.9"

    assert slack.posted[0]["thread_ts"] == CARD
    assert slack.posted[0]["text"] == "1 linked message"
    assert conn.args_for("SET unfurl_ts")[0][0] == "9.9"


def test_unfurl_existing_reply_with_changed_digest_updates_message():
    conn, slack = unfurl_setup((7, "9.9", "stale", at(0)), (1, f"<{LINK}>", at(-5), CARD, None)), Slack()

    assert channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD) == "9.9"

    assert slack.posted == []
    assert slack.updated[0]["ts"] == "9.9"


def test_unfurl_message_with_unfurled_at_and_no_reply_does_nothing():
    conn, slack = unfurl_setup((7, None, None, at(0)), (1, f"<{LINK}>", at(-5), CARD, None)), Slack()

    assert channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD) is None
    assert slack.posted == [] and slack.updated == []


def test_unfurl_message_without_links_marks_settled_without_reply():
    conn, slack = unfurl_setup((7, None, None, None), (1, "no links", at(-5), CARD, None)), Slack()
    conn.answers["s.raw"] = []

    assert channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD) is None
    assert slack.posted == []
    assert conn.args_for("SET unfurl_ts") == [(None, None, 1)]


LINKED_TS = "1786970526.885769"
LINKED_MESSAGE = {"ts": LINKED_TS, "text": "the linked message", "user": "UAUTHOR"}


def link_message(state, inside=True):
    conn = unfurl_setup(state, (1, f"<{LINK}>", at(-5), CARD, None))
    conn.answers["kind = 'link' AND NOT is_reachable"] = [(40, "C0BNYU3JK3Q", LINKED_TS, None)]
    conn.answers["FROM fd.channel_membership WHERE channel_id"] = [(inside,)]
    return conn


def test_unfurl_reads_unread_link_before_first_post():
    conn, slack = link_message((7, None, None, None)), Slack([LINKED_MESSAGE])

    assert channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD) == "9.9"

    assert slack.calls == [("history", "C0BNYU3JK3Q"), ("post", CHANNEL_ID)]
    assert conn.args_for("SET source_author_user_id") == [("UAUTHOR", "the linked message", 40)]


def test_unfurl_joins_public_channel_before_reading_link():
    conn, slack = link_message((7, None, None, None), inside=False), Slack([LINKED_MESSAGE])

    channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD)

    assert [name for name, _ in slack.calls] == ["join", "history", "post"]
    assert slack.calls[0] == ("join", "C0BNYU3JK3Q")


def test_unfurl_does_not_join_known_private_channel():
    conn, slack = link_message((7, None, None, None), inside=False), Slack()
    conn.answers["FROM raw.channel_dim"] = [(1,)]

    channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD)

    assert [name for name, _ in slack.calls] == ["history", "post"]
    assert conn.args_for("SET source_author_user_id") == []


def test_unfurl_existing_reply_reads_no_links():
    conn, slack = link_message((7, "9.9", "stale", at(0))), Slack([LINKED_MESSAGE])

    channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD)

    assert conn.args_for("NOT is_reachable") == []
    assert slack.calls == [] and slack.updated[0]["ts"] == "9.9"


def test_has_unmirrored_content_sql_includes_forward_kind():
    assert "kind = 'forward'" in channel.HAS_UNMIRRORED_CONTENT


def test_waiting_sql_excludes_card_message():
    assert "IS DISTINCT FROM 'card'" in chat.WAITING
    assert "IS DISTINCT FROM 'card'" in chat.WAITING_ANYWHERE


def test_parse_command_open_without_member_returns_none_member():
    assert command.parse_command("open a raid in the lounge") == ("open", None, "a raid in the lounge")
    assert command.case_opened_text(5, None) == "*Case 5* opened"
    assert command.case_opened_text(5, "UBOB") == "*Case 5* opened by <@UBOB>"


def test_parse_command_lookup_requires_member():
    verb, case_id, _ = command.parse_command("lookup the lounge")
    assert (verb, case_id) == ("lookup", None)
    assert verb in command.MEMBER_REQUIRED_VERBS


def test_post_follow_up_numbered_links_disable_slack_unfurl(monkeypatch):
    conn = Conn({
        "r.is_anonymous, r.reporter_user_id": [(f"also <{OTHER}>", None, CARD, 7, True, None, None)],
        **conversation((1, "the report", at(-5), CARD, None), (2, f"also <{OTHER}>", at(1), None, None)),
    })
    monkeypatch.setattr(channel, "unfurl", lambda *args: None)
    slack = Slack()

    channel.post_follow_up(slack, conn, 2, CHANNEL_ID)

    message = slack.posted[0]
    assert message["text"] == f"also <{OTHER}> (1)"
    assert message["unfurl_links"] is False, "slack would draw the same message a second time"


def test_reply_blocks_forward_item_renders_number_quote_and_author():
    forward_share = {"kind": "forward", "source_channel_id": "C0FWD0000", "source_ts": "1786970700.000200",
                     "permalink": LINK}
    numbered = linked.numbering("", [forward_share], 1)
    blocks = linked.reply_blocks(linked.items(numbered, [dict(forward(), permalink=LINK)]))

    head, quote_block = blocks[0]["elements"]
    assert head["elements"][1]["text"] == " (1)"
    assert quote_block["elements"] == [{"type": "text", "text": "mwah"}]
    assert blocks[1]["elements"][0]["text"] == "<@UDRACULA> in <#C0FWD0000>"


def forwarded_with(*files):
    return dict(forward(), permalink=LINK, raw={"files": [{"id": one} for one in files]})


def test_reply_blocks_forwarded_image_renders_image_block():
    full = forwarded_with("F1")
    items = linked.items(linked.numbering("", [full], 1), [full])
    uploads = {"F1": {"id": "FUP1", "name": "image.png", "image": True}}

    blocks = linked.reply_blocks(items, uploads)

    assert [b["type"] for b in blocks] == ["rich_text", "image", "context"]
    assert blocks[1] == {"type": "image", "slack_file": {"id": "FUP1"}, "alt_text": "image.png"}


def test_reply_blocks_forwarded_document_renders_file_name():
    full = forwarded_with("F2")
    items = linked.items(linked.numbering("", [full], 1), [full])

    blocks = linked.reply_blocks(items, {"F2": {"id": None, "name": "notes.pdf", "image": False}})

    assert blocks[1]["elements"][0]["text"] == "Files: notes.pdf"


def test_reply_blocks_forwarded_image_without_upload_renders_no_image_block():
    full = forwarded_with("F1")
    items = linked.items(linked.numbering("", [full], 1), [full])

    assert [b["type"] for b in linked.reply_blocks(items, {})] == ["rich_text", "context"]


def test_reply_blocks_images_count_toward_block_limit():
    full = forwarded_with("F1", "F2", "F3")
    uploads = {one: {"id": f"U{one}", "name": "x.png", "image": True} for one in ("F1", "F2", "F3")}
    items = linked.items(linked.numbering("", [full] * 12, 1), [full])

    blocks = linked.reply_blocks(items, uploads)

    assert len(blocks) <= 50
    assert blocks[-1]["elements"][0]["text"].endswith("more in Fire Engine")


class Uploading(Slack):
    def files_upload_v2(self, **kwargs):
        self.posted.append(("upload", kwargs))
        return {"files": [{"id": "FUP1"}]}


def test_forwarded_files_uploads_image_once_and_reuses_mirrored_file(monkeypatch):
    monkeypatch.setattr(channel.attachments.blobs, "body_of", lambda conn, sha: (b"png", "image/png"))
    monkeypatch.setattr(channel.time, "sleep", lambda seconds: None)
    slack = Uploading()
    conn = Conn({"mf.forwarded AND f.fetch_state": [(5, "F1", "image.png", "image/png", "abc", None)]})

    uploads = channel.forwarded_files(slack, conn, 80)

    assert uploads == {"F1": {"id": "FUP1", "name": "image.png", "image": True}}
    assert conn.args_for("SET mirrored_file_id") == [("FUP1", 80, 5)]

    conn = Conn({"mf.forwarded AND f.fetch_state": [(5, "F1", "image.png", "image/png", "abc", "FUP1")]})
    slack = Uploading()
    assert channel.forwarded_files(slack, conn, 80)["F1"]["id"] == "FUP1"
    assert slack.posted == [], "an image already up is reused"


def test_follow_ups_sql_selects_every_message_except_card_message():
    for sql in (channel.FOLLOW_UPS_WAITING, channel.FOLLOW_UPS_ANYWHERE):
        assert "m.posted_at > c.handed_off_at" not in sql
        assert "m.id <> (" in sql and "first_inbound.direction = 'inbound'" in sql
        assert "m.deleted_at IS NULL" in sql and "m.mirrored_ts IS NULL" in sql
