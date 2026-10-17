import pytest

from bot.nemo import case_queue

FIREHOUSE_ID = "C_FIRE"
THREAD = "100.000"


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

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class Slack:
    def __init__(self):
        self.posted = []
        self.reactions = []

    def chat_postMessage(self, **kwargs):
        self.posted.append(kwargs)
        return {"ts": "9.9"}

    def reactions_add(self, **kwargs):
        self.reactions.append(kwargs)

    def reactions_remove(self, **kwargs):
        self.reactions.append(dict(kwargs, removed=True))


@pytest.fixture(autouse=True)
def firehouse(monkeypatch):
    monkeypatch.setattr(case_queue, "firehouse_channel", lambda conn=None: FIREHOUSE_ID)


@pytest.fixture(autouse=True)
def stub_posting_identity(monkeypatch):
    monkeypatch.setattr(
        case_queue, "author_display_fields", lambda client, anonymous, user_id: {"username": user_id}
    )


def case_rows(card_ts=None, reported=False, opening=None):
    return {
        "SELECT id, category_key": (41, None, None, None, card_ts, None, "UOPENER", None, None,
                                    None, None),
        "FOR UPDATE": (card_ts,),
        "NOT EXISTS (SELECT 1 FROM fd.case_reports": None if reported or card_ts else (1,),
        "mirrored_as = 'card'": opening,
    }


def test_post_missing_card_without_report_posts_to_firehouse_channel():
    conn, slack = Conn(case_rows()), Slack()

    ts = case_queue.post_missing_card(slack, conn, 41)

    assert ts == "9.9"
    assert slack.posted[0]["channel"] == FIREHOUSE_ID
    assert slack.posted[0]["thread_ts"] is None
    assert conn.args_for("UPDATE fd.cases SET card_channel_id")[0][:3] == (FIREHOUSE_ID, None, "9.9")


def test_post_missing_card_with_channel_argument_posts_to_that_channel():
    conn, slack = Conn(case_rows()), Slack()

    case_queue.post_missing_card(slack, conn, 41, "C_ELSE")

    assert slack.posted[0]["channel"] == "C_ELSE"


def test_post_missing_card_with_report_returns_none():
    conn, slack = Conn(case_rows(reported=True)), Slack()

    assert case_queue.post_missing_card(slack, conn, 41) is None
    assert slack.posted == []


def test_post_with_existing_card_returns_card_ts_without_posting():
    conn, slack = Conn(case_rows(card_ts="8.8")), Slack()

    assert case_queue.post_missing_card(slack, conn, 41) is None
    assert case_queue.post(slack, conn, 41, FIREHOUSE_ID) == "8.8"
    assert slack.posted == []


def test_post_with_card_ts_set_concurrently_returns_that_ts_without_posting():
    conn, slack = Conn(case_rows()), Slack()
    conn.rows["FOR UPDATE"] = ("7.7",)

    assert case_queue.post(slack, conn, 41, FIREHOUSE_ID) == "7.7"
    assert slack.posted == []


def test_post_with_thread_ts_posts_in_thread():
    conn, slack = Conn(case_rows()), Slack()

    case_queue.post(slack, conn, 41, "C1", THREAD)

    assert slack.posted[0]["thread_ts"] == THREAD
    assert conn.args_for("UPDATE fd.cases SET card_channel_id")[0][:3] == ("C1", THREAD, "9.9")


def test_post_missing_card_with_opening_message_posts_quote_as_opener():
    conn, slack = Conn(case_rows(opening=(7, "kept posting invite links"))), Slack()

    case_queue.post_missing_card(slack, conn, 41)

    card_post, header = slack.posted
    assert card_post["username"] == "UOPENER"
    assert [b["type"] for b in card_post["blocks"]] == ["rich_text"]
    assert "kept posting invite links" in str(card_post["blocks"][0])
    assert header["thread_ts"] == "9.9" and header["text"] == "Case 41, open"
    assert conn.args_for("UPDATE fd.case_chat SET mirrored_ts") == [("9.9", 7)]


def test_post_missing_card_without_opening_message_posts_case_card():
    conn, slack = Conn(case_rows()), Slack()

    case_queue.post_missing_card(slack, conn, 41)

    assert "username" not in slack.posted[0]
    assert [b["type"] for b in slack.posted[0]["blocks"]] == ["card"]
    assert conn.args_for("UPDATE fd.case_chat SET mirrored_ts") == []


def test_post_missing_card_adds_hourglass_reaction():
    conn, slack = Conn(case_rows()), Slack()

    case_queue.post_missing_card(slack, conn, 41)

    assert slack.reactions == [{"channel": FIREHOUSE_ID, "timestamp": "9.9",
                              "name": "hourglass_flowing_sand"}]


def test_post_with_thread_ts_adds_no_reaction():
    conn, slack = Conn(case_rows()), Slack()

    case_queue.post(slack, conn, 41, "C1", THREAD)

    assert slack.reactions == [], "the hourglass that opened the case is already on that message"


def resolved_thread_rows(resolution="no_action"):
    rows = case_rows(card_ts="8.8")
    rows["SELECT id, category_key"] = (41, None, "2026-10-11", "C1", "8.8", "old", "UOPENER",
                                       resolution, THREAD, None, None)
    return rows


class UpdatableSlack(Slack):
    def chat_update(self, **kwargs):
        return {"ok": True}

    def reactions_get(self, **kwargs):
        return {"message": {"reactions": []}}


def test_refresh_card_resolved_thread_case_adds_check_on_thread_message():
    conn, slack = Conn(resolved_thread_rows()), UpdatableSlack()

    case_queue.refresh_card(slack, conn, 41)

    added = [one for one in slack.reactions if not one.get("removed")]
    assert added == [{"channel": "C1", "timestamp": THREAD, "name": "white_check_mark"}]
    removed_reactions = {one["name"] for one in slack.reactions
                         if one.get("removed") and one["timestamp"] == "8.8"}
    assert "hourglass_flowing_sand" in removed_reactions, "nemo's own hourglass leaves the card"


def test_refresh_card_duplicate_thread_case_adds_repeat_reaction():
    conn, slack = Conn(resolved_thread_rows("duplicate")), UpdatableSlack()

    case_queue.refresh_card(slack, conn, 41)

    assert [one["name"] for one in slack.reactions
            if not one.get("removed")] == ["repeat"]
