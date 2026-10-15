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
        self.reacted = []

    def chat_postMessage(self, **kwargs):
        self.posted.append(kwargs)
        return {"ts": "9.9"}

    def reactions_add(self, **kwargs):
        self.reacted.append(kwargs)

    def reactions_remove(self, **kwargs):
        self.reacted.append(dict(kwargs, removed=True))


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
                                    None),
        "FOR UPDATE": (card_ts,),
        "NOT EXISTS (SELECT 1 FROM fd.case_reports": None if reported or card_ts else (1,),
        "mirrored_as = 'card'": opening,
    }


def test_a_case_opened_without_a_report_gets_a_card_in_the_firehouse():
    conn, slack = Conn(case_rows()), Slack()

    ts = case_queue.card(slack, conn, 41)

    assert ts == "9.9"
    assert slack.posted[0]["channel"] == FIREHOUSE_ID
    assert slack.posted[0]["thread_ts"] is None
    assert conn.args_for("UPDATE fd.cases SET card_channel_id")[0][:3] == (FIREHOUSE_ID, None, "9.9")


def test_a_card_can_be_sent_somewhere_other_than_the_firehouse():
    conn, slack = Conn(case_rows()), Slack()

    case_queue.card(slack, conn, 41, "C_ELSE")

    assert slack.posted[0]["channel"] == "C_ELSE"


def test_a_case_that_came_in_as_a_report_is_left_to_its_report_card():
    conn, slack = Conn(case_rows(reported=True)), Slack()

    assert case_queue.card(slack, conn, 41) is None
    assert slack.posted == []


def test_a_case_that_already_has_a_card_does_not_get_a_second_one():
    conn, slack = Conn(case_rows(card_ts="8.8")), Slack()

    assert case_queue.card(slack, conn, 41) is None
    assert case_queue.post(slack, conn, 41, FIREHOUSE_ID) == "8.8"
    assert slack.posted == []


def test_a_card_claimed_while_we_were_asking_is_left_alone():
    conn, slack = Conn(case_rows()), Slack()
    conn.rows["FOR UPDATE"] = ("7.7",)

    assert case_queue.post(slack, conn, 41, FIREHOUSE_ID) == "7.7"
    assert slack.posted == []


def test_a_thread_card_still_goes_into_its_thread():
    conn, slack = Conn(case_rows()), Slack()

    case_queue.post(slack, conn, 41, "C1", THREAD)

    assert slack.posted[0]["thread_ts"] == THREAD
    assert conn.args_for("UPDATE fd.cases SET card_channel_id")[0][:3] == ("C1", THREAD, "9.9")


def test_what_happened_is_quoted_on_the_card_in_the_openers_name():
    conn, slack = Conn(case_rows(opening=(7, "kept posting invite links"))), Slack()

    case_queue.card(slack, conn, 41)

    card_post, header = slack.posted
    assert card_post["username"] == "UOPENER"
    assert [b["type"] for b in card_post["blocks"]] == ["rich_text"]
    assert "kept posting invite links" in str(card_post["blocks"][0])
    assert header["thread_ts"] == "9.9" and header["text"] == "Case 41"
    assert conn.args_for("UPDATE fd.case_chat SET mirrored_ts") == [("9.9", 7)]


def test_a_card_with_nothing_said_goes_up_as_nemo():
    conn, slack = Conn(case_rows()), Slack()

    case_queue.card(slack, conn, 41)

    assert "username" not in slack.posted[0]
    assert [b["type"] for b in slack.posted[0]["blocks"]] == ["section"]
    assert conn.args_for("UPDATE fd.case_chat SET mirrored_ts") == []


def test_a_new_card_waits_with_an_hourglass():
    conn, slack = Conn(case_rows()), Slack()

    case_queue.card(slack, conn, 41)

    assert slack.reacted == [{"channel": FIREHOUSE_ID, "timestamp": "9.9",
                              "name": "hourglass_flowing_sand"}]


def test_a_thread_card_leaves_the_tracking_to_the_message_it_answers():
    conn, slack = Conn(case_rows()), Slack()

    case_queue.post(slack, conn, 41, "C1", THREAD)

    assert slack.reacted == [], "the hourglass that opened the case is already on that message"


def resolved_in_thread(resolution="no_action"):
    rows = case_rows(card_ts="8.8")
    rows["SELECT id, category_key"] = (41, None, "2026-10-11", "C1", "8.8", "old", "UOPENER",
                                       resolution, THREAD, None)
    return rows


class Updating(Slack):
    def chat_update(self, **kwargs):
        return {"ok": True}

    def reactions_get(self, **kwargs):
        return {"message": {"reactions": []}}


def test_a_resolved_thread_case_is_checked_on_the_message_it_answers():
    conn, slack = Conn(resolved_in_thread()), Updating()

    case_queue.refresh_card(slack, conn, 41)

    added = [one for one in slack.reacted if not one.get("removed")]
    assert added == [{"channel": "C1", "timestamp": THREAD, "name": "white_check_mark"}]
    removed_reactions = {one["name"] for one in slack.reacted
                         if one.get("removed") and one["timestamp"] == "8.8"}
    assert "hourglass_flowing_sand" in removed_reactions, "nemo's own hourglass leaves the card"


def test_a_merged_thread_case_shows_the_repeat_on_its_message():
    conn, slack = Conn(resolved_in_thread("duplicate")), Updating()

    case_queue.refresh_card(slack, conn, 41)

    assert [one["name"] for one in slack.reacted
            if not one.get("removed")] == ["repeat"]
