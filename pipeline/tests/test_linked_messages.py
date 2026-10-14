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


def share(**over):
    share_row = {"kind": "unfurl", "source_channel_id": "C0BNYU3JK3Q", "source_channel_name": None,
                 "source_ts": "1786970526.885769", "is_reachable": True,
                 "source_author_user_id": "UDRACULA", "source_body": "mwah", "permalink": LINK}
    share_row.update(over)
    return share_row


def forward(**over):
    return share(kind="forward", source_channel_id="C0FWD0000", source_ts="1786970700.000200",
                 permalink=None, **over)


def runs(block):
    return block["elements"][0]["elements"]


def numbers_in(block):
    return [run["text"] for run in runs(block) if run["type"] == "text" and "(" in run["text"]]


def card(body, blocks=None, shares=()):
    case = {"case_id": 23, "body": body, "blocks": blocks, "shares": list(shares),
            "subjects": [], "assignees": [], "category_key": None,
            "numbering": linked.numbering(body, list(shares), 1)}
    return report.build_blocks(case)


def test_the_same_link_twice_is_numbered_twice():
    built = card(f"test <{LINK}> test <{LINK}> test meow")
    assert numbers_in(built[0]) == [" (1)", " (2)"]


def test_numbers_sit_right_after_their_link():
    built = card(f"test <{LINK}> test")
    kinds = [(run["type"], run.get("text")) for run in runs(built[0])]
    assert kinds == [("text", "test "), ("link", None), ("text", " (1)"), ("text", " test")]


def mention():
    return {"type": "message_mention", "url": LINK, "text": LINK, "author_id": "UDRACULA",
            "channel_id": "C0BNYU3JK3Q", "message_ts": "1786970526.885769"}


def test_slacks_own_rich_text_is_numbered_too():
    blocks = [{"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [
        {"type": "text", "text": "test "},
        mention(),
        {"type": "text", "text": " test "},
        {"type": "link", "url": LINK},
    ]}]}]
    built = card(f"test <{LINK}|{LINK}> test <{LINK}>", blocks=blocks)
    assert numbers_in(built[0]) == [" (1)", " (2)"]


def test_a_link_slack_labels_with_itself_counts_once():
    text = f"test <{LINK}|{LINK}> test <{LINK}|{LINK}> test <{LINK}|{LINK}>"
    numbered = linked.numbering(text, [share()], 1)

    assert linked.size(numbered) == 3
    assert [one["url"] for one in numbered["links"]] == [LINK] * 3
    assert linked.numbered_text(f"<{LINK}|{LINK}>", linked.numbering(f"<{LINK}|{LINK}>", [], 7)) \
        == f"<{LINK}|{LINK}> (7)"


def test_a_link_to_anywhere_but_slack_is_left_alone():
    built = card("see <https://example.com>")
    assert numbers_in(built[0]) == []


def test_a_follow_up_carries_on_from_where_the_count_stopped():
    text = f"also <{OTHER}>"
    assert linked.numbered_text(text, linked.numbering(text, [], 3)) == f"also <{OTHER}> (3)"


def test_a_forward_takes_the_next_number_after_the_links():
    text = f"look <{LINK}>"
    numbered = linked.numbering(text, [share(), forward()], 1)
    assert linked.numbered_text(text, numbered) == f"look <{LINK}> (1)\nforwarded (2)"


def test_a_forward_of_a_linked_message_is_not_counted_twice():
    numbered = linked.numbering(f"look <{LINK}>", [share(kind="forward")], 1)
    assert linked.size(numbered) == 1


def test_a_report_that_is_only_a_forward_still_has_a_quote():
    built = card("", shares=[forward()])
    assert [run["text"] for run in runs(built[0])] == ["forwarded (1)"]


def test_each_link_is_unfurled_with_its_number_its_words_and_who_said_it():
    text = f"test <{LINK}> test <{LINK}>"
    items = linked.items(linked.numbering(text, [share()], 1), [share()])
    blocks = linked.reply_blocks(items)

    assert [b["type"] for b in blocks] == ["rich_text", "context"] * 2
    head, words = blocks[0]["elements"]
    assert head["elements"] == [{"type": "link", "url": LINK}, {"type": "text", "text": " (1)"}]
    assert words["type"] == "rich_text_quote"
    assert words["elements"] == [{"type": "text", "text": "mwah"}]
    assert blocks[1]["elements"][0]["text"] == "<@UDRACULA> in <#C0BNYU3JK3Q>"
    assert blocks[2]["elements"][0]["elements"][1]["text"] == " (2)"


def test_a_link_nemo_could_not_read_says_so():
    text = f"look <{LINK}>"
    unreachable = share(kind="link", is_reachable=False, source_body=None, permalink=None)
    blocks = linked.reply_blocks(linked.items(linked.numbering(text, [unreachable], 1), [unreachable]))

    assert len(blocks[0]["elements"]) == 1, "no empty quote"
    assert blocks[1]["elements"][0]["text"] == "Message not accessible"


def test_a_long_list_stops_short_of_slacks_block_limit():
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
    def __init__(self):
        self.posted = []
        self.updated = []

    def chat_postMessage(self, **kwargs):
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


def test_numbers_run_on_across_the_report_and_its_follow_ups():
    conn = Conn(conversation(
        (1, f"<{LINK}> and <{LINK}>", at(-5), CARD, None),
        (2, f"before it went up <{OTHER}>", at(-1), None, None),
        (3, f"later <{OTHER}>", at(1), "3.3", None),
        (4, f"gone <{OTHER}>", at(2), None, at(3)),
        (5, f"and <{LINK}>", at(4), None, None),
    ))

    numbers = channel.numbers(conn, 7)

    assert sorted(numbers) == [1, 3, 5], "only what reaches the thread is counted"
    assert [numbers[one]["start"] for one in (1, 3, 5)] == [1, 3, 4]


def unfurl_setup(state, *rows):
    answers = conversation(*rows)
    answers["unfurl_digest, unfurled_at"] = [state]
    answers["s.raw"] = [tuple(share().get(key) for key in (
        "kind", "source_channel_id", "source_channel_name", "source_ts", "permalink",
        "is_reachable", "source_author_user_id", "source_body")) + (None,)]
    return Conn(answers)


def test_links_are_unfurled_once_in_the_thread_under_the_card():
    conn, slack = unfurl_setup((7, None, None, None), (1, f"<{LINK}>", at(-5), CARD, None)), Slack()

    assert channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD) == "9.9"

    assert slack.posted[0]["thread_ts"] == CARD
    assert slack.posted[0]["text"] == "1 linked message"
    assert conn.args_for("SET unfurl_ts")[0][0] == "9.9"


def test_a_reply_already_up_is_redrawn_when_its_words_change():
    conn, slack = unfurl_setup((7, "9.9", "stale", at(0)), (1, f"<{LINK}>", at(-5), CARD, None)), Slack()

    assert channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD) == "9.9"

    assert slack.posted == []
    assert slack.updated[0]["ts"] == "9.9"


def test_a_message_settled_before_unfurls_existed_is_left_alone():
    conn, slack = unfurl_setup((7, None, None, at(0)), (1, f"<{LINK}>", at(-5), CARD, None)), Slack()

    assert channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD) is None
    assert slack.posted == [] and slack.updated == []


def test_a_message_with_no_links_is_settled_without_a_reply():
    conn, slack = unfurl_setup((7, None, None, None), (1, "no links", at(-5), CARD, None)), Slack()
    conn.answers["s.raw"] = []

    assert channel.unfurl(slack, conn, 1, CHANNEL_ID, CARD) is None
    assert slack.posted == []
    assert conn.args_for("SET unfurl_ts") == [(None, None, 1)]


def test_a_follow_up_that_is_only_a_forward_still_goes_into_the_thread():
    assert "kind = 'forward'" in channel.HAS_UNMIRRORED_CONTENT


def test_the_opening_message_is_never_mirrored_under_its_own_card():
    assert "IS DISTINCT FROM 'card'" in chat.WAITING
    assert "IS DISTINCT FROM 'card'" in chat.WAITING_ANYWHERE


def test_a_case_can_be_opened_about_nobody():
    assert command.parse_command("open a raid in the lounge") == ("open", None, "a raid in the lounge")
    assert command.opened(5, None) == "*case 5* opened"
    assert command.opened(5, "UBOB") == "*case 5* opened about <@UBOB>"


def test_the_other_verbs_still_need_somebody():
    verb, case_id, _ = command.parse_command("lookup the lounge")
    assert (verb, case_id) == ("lookup", None)
    assert verb in command.ABOUT_SOMEBODY


def test_a_follow_up_with_numbered_links_leaves_the_unfurling_to_nemo(monkeypatch):
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


def test_a_forward_is_unfurled_with_its_words():
    forward_share = {"kind": "forward", "source_channel_id": "C0FWD0000", "source_ts": "1786970700.000200",
                     "permalink": LINK}
    numbered = linked.numbering("", [forward_share], 1)
    blocks = linked.reply_blocks(linked.items(numbered, [dict(forward(), permalink=LINK)]))

    head, words = blocks[0]["elements"]
    assert head["elements"][1]["text"] == " (1)"
    assert words["elements"] == [{"type": "text", "text": "mwah"}]
    assert blocks[1]["elements"][0]["text"] == "<@UDRACULA> in <#C0FWD0000>"


def forwarded_with(*files):
    return dict(forward(), permalink=LINK, raw={"files": [{"id": one} for one in files]})


def test_a_forwarded_picture_sits_inside_its_forward():
    full = forwarded_with("F1")
    items = linked.items(linked.numbering("", [full], 1), [full])
    uploads = {"F1": {"id": "FUP1", "name": "image.png", "image": True}}

    blocks = linked.reply_blocks(items, uploads)

    assert [b["type"] for b in blocks] == ["rich_text", "image", "context"]
    assert blocks[1] == {"type": "image", "slack_file": {"id": "FUP1"}, "alt_text": "image.png"}


def test_a_forwarded_document_is_named_inside_its_forward():
    full = forwarded_with("F2")
    items = linked.items(linked.numbering("", [full], 1), [full])

    blocks = linked.reply_blocks(items, {"F2": {"id": None, "name": "notes.pdf", "image": False}})

    assert blocks[1]["elements"][0]["text"] == "Files: notes.pdf"


def test_a_picture_not_downloaded_yet_leaves_no_gap():
    full = forwarded_with("F1")
    items = linked.items(linked.numbering("", [full], 1), [full])

    assert [b["type"] for b in linked.reply_blocks(items, {})] == ["rich_text", "context"]


def test_pictures_count_toward_slacks_block_limit():
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


def test_a_forwarded_picture_is_uploaded_once(monkeypatch):
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
