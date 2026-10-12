from bot.nemo import case_queue, channel


class Conn:
    def __init__(self, answers=None):
        self.answers = answers or {}
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        for mark, row in self.answers.items():
            if mark in self.executed[-1][0]:
                return row
        return None

    def fetchall(self):
        row = self.fetchone()
        return [row] if row else []

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


class Slack:
    def __init__(self, refusal=None):
        self.refusal = refusal
        self.calls = []

    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append((name, kwargs))
            if name == "chat_update" and self.refusal:
                raise RuntimeError(self.refusal)
            return {"ts": "9.9", "ok": True}
        return call

    def calls_to(self, name):
        return [kwargs for method, kwargs in self.calls if method == name]


def report_case(**over):
    case = {"case_id": 15, "report_id": 10, "forwarded_ts": "1.1", "card_digest": "old",
            "card_channel_id": "C_OLD", "body": "test", "blocks": None, "shares": [],
            "assignees": [], "resolved_at": None, "resolution": None, "url": None}
    case.update(over)
    return case


def test_a_card_slack_will_not_edit_is_left_as_it_is(monkeypatch):
    monkeypatch.setattr(channel, "gather", lambda conn, case_id: report_case())
    conn, slack = Conn(), Slack("cant_update_message")

    assert channel.refresh_card(slack, conn, 15) == "1.1"

    assert slack.calls_to("chat_postMessage") == [], "never a second card"
    assert conn.args_for("SET forwarded_ts = NULL") == []
    assert conn.args_for("SET card_digest = %s")[0][1] == 10, "kept as drawn so the sweep moves on"


def test_a_report_card_is_edited_where_it_was_posted(monkeypatch):
    monkeypatch.setattr(channel, "gather", lambda conn, case_id: report_case())
    slack = Slack()

    channel.refresh_card(slack, Conn(), 15, "C_NOW")

    assert slack.calls_to("chat_update")[0]["channel"] == "C_OLD"


def test_a_new_report_card_remembers_its_channel(monkeypatch):
    monkeypatch.setattr(channel, "gather", lambda conn, case_id: report_case(
        forwarded_ts=None, card_channel_id=None, is_anonymous=True, reporter_user_id=None,
        message_id=None))
    conn = Conn()

    channel.post_report(Slack(), conn, 15, "C_NOW")

    assert conn.args_for("SET forwarded_ts = %s")[0][:3][2] == "C_NOW"


def test_threads_follow_the_report_card_into_its_channel():
    assert "r.card_channel_id" in channel.CARD_ROOM
    for query in (channel.FOLLOW_UP, channel.FILES_ON_CASE, channel.UNFURLS_ON_CASE):
        assert "r.card_channel_id" in query


def staff_case(card_ts="8.8"):
    return {"SELECT id, category_key": (41, None, None, "C_FIRE", card_ts, "old", "UME", None, None,
                                        None)}


def test_a_staff_card_keeps_its_place_when_slack_refuses(monkeypatch):
    conn, slack = Conn(staff_case()), Slack("message_not_found")

    assert case_queue.refresh_card(slack, conn, 41) == "8.8"

    assert conn.args_for("card_ts = NULL") == []
    assert conn.args_for("SET card_digest = %s"), "a refusal is not retried every sweep"


def test_a_staff_card_retries_after_a_passing_failure(monkeypatch):
    conn, slack = Conn(staff_case()), Slack("ratelimited")

    assert case_queue.refresh_card(slack, conn, 41) == "8.8"

    assert conn.args_for("SET card_digest = %s") == []
