import datetime as dt

import pytest

from bot.nemo import command, open_cases
from bot.nemo.views import open_cases as view

NOW = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.UTC)
CASE_URL = "https://fe.example/fd/cases/"
REPORT_URL = "https://hackclub.slack.com/archives/C_FIRE/p1760000000000100"


def make_case(case_id, category_key=None, hours=3, assignees=(), entries=None, has_reports=True):
    return {"case_id": case_id, "category_key": category_key, "opened_at": NOW - dt.timedelta(hours=hours),
            "assignees": list(assignees), "url": f"{CASE_URL}{case_id}",
            "entries": entries if entries is not None else [{"body": "spam in #lounge", "url": REPORT_URL}],
            "has_reports": has_reports}


def rich_text_lists(message):
    return [element for element in message["blocks"][0]["elements"] if element["type"] == "rich_text_list"]


def test_build_message_nests_entries_under_cases():
    message = view.build_message(
        2, [make_case(4913, "spam", hours=76), make_case(4920, assignees=["UMOD", "UTWO"])], {}, now=NOW)

    assert message["text"] == "Open cases (2)"
    lists = rich_text_lists(message)
    assert [element["indent"] for element in lists] == [0, 1, 0, 1]
    first_case = lists[0]["elements"][0]["elements"]
    assert first_case[0] == {"type": "link", "url": f"{CASE_URL}4913", "text": "Case 4913", "style": {"bold": True}}
    assert first_case[1]["text"] == " · Spam, mass pings or invites · 3d 4h ago"
    assert lists[1]["elements"][0]["elements"] == [{"type": "link", "url": REPORT_URL, "text": "spam in #lounge"}]
    second_case = lists[2]["elements"][0]["elements"]
    assert [element.get("text") or element.get("user_id") for element in second_case[1:]] == \
        [" · 3h 0m ago · Assigned: ", "UMOD", ", ", "UTWO"]


def test_build_message_report_without_body_uses_report_label():
    entries = [{"body": None, "url": REPORT_URL}, {"body": "second report", "url": None}]

    lists = rich_text_lists(view.build_message(1, [make_case(1, entries=entries)], {}, now=NOW))

    assert [section["elements"] for section in lists[1]["elements"]] == [
        [{"type": "link", "url": REPORT_URL, "text": view.REPORT_LABEL}],
        [{"type": "text", "text": "second report"}],
    ]


def test_build_message_card_without_body_uses_card_label():
    case = make_case(1, entries=[{"body": "", "url": REPORT_URL}], has_reports=False)

    lists = rich_text_lists(view.build_message(1, [case], {}, now=NOW))

    assert lists[1]["elements"][0]["elements"][0]["text"] == view.CARD_LABEL


def test_build_message_without_entries_omits_nested_list():
    lists = rich_text_lists(view.build_message(1, [make_case(1, entries=[])], {}, now=NOW))

    assert [element["indent"] for element in lists] == [0]


def test_build_message_over_limit_shows_count_and_list_link():
    message = view.build_message(61, [make_case(1)], {}, now=NOW, list_url="https://fe.example/fd/cases?view=attention")

    assert message["blocks"][1] == {"type": "context", "elements": [{"type": "mrkdwn", "text": "showing 1 of 61"}]}
    assert message["blocks"][2]["elements"][0]["url"] == "https://fe.example/fd/cases?view=attention"


def test_build_message_without_cases_returns_empty_title():
    assert view.build_message(0, [], {}) == {
        "text": view.EMPTY_TITLE,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "No open cases"}}],
    }


@pytest.mark.parametrize(("body", "expected"), [
    ("short", "short"),
    ("someone keeps pinging @channel in #lounge every few minutes", "someone keeps pinging @channel in #lounge every..."),
    ("<@U1> told <@U2|bo> to go to <#C1> and <#C2|code>", "@Ana told @bo to go to #lounge and #code"),
    ("<!here> see <https://x.example/a|this> and <https://y.example/b>", "@here see this and https://y.example/b"),
    ("a &lt;b&gt; &amp;\n\n  c", "a <b> & c"),
    ("x" * 60, "x" * 50 + "..."),
    (None, ""),
])
def test_snippet_converts_slack_markup_and_truncates(body, expected):
    assert view.snippet(body, {"U1": "Ana", "C1": "lounge"}) == expected


def test_mention_ids_returns_user_and_channel_ids():
    assert view.mention_ids(["<@U2> in <#C1|x>", "<@U1|a> <@U2>", None]) == (["U1", "U2"], ["C1"])


class FakeConn:
    def __init__(self, results):
        self.results = results
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        self.sql = sql
        return self

    def fetchone(self):
        return self.results[self.sql]

    def fetchall(self):
        return self.results.get(self.sql, [])


def test_fetch_open_cases_uses_reports_or_card_opening(monkeypatch):
    monkeypatch.setattr(open_cases, "case_url", lambda case_id: f"{CASE_URL}{case_id}")
    opened_at = NOW - dt.timedelta(days=1)
    conn = FakeConn({
        open_cases.OPEN_CASE_COUNT: (30,),
        open_cases.OPEN_CASES: [(1, "spam", opened_at, None, None, None, ["UMOD"]),
                                (2, None, opened_at, "C_FIRE", "1760000000.000200", None, []),
                                (3, None, opened_at, None, None, None, [])],
        open_cases.CASE_REPORTS: [(1, "first", "C_FIRE", "1760000000.000100"), (1, "second", "C_FIRE", None)],
        open_cases.CARD_OPENING_BODIES: [(2, "opened by hand")],
    })

    total, cases = open_cases.fetch_open_cases(conn)

    assert total == 30
    assert conn.executed[1][1] == (open_cases.CASE_LIMIT,)
    assert conn.executed[2][1] == ([1, 2, 3], open_cases.REPORTS_PER_CASE)
    assert cases[0]["entries"] == [{"body": "first", "url": REPORT_URL}, {"body": "second", "url": None}]
    assert cases[0]["has_reports"] is True and cases[0]["assignees"] == ["UMOD"]
    assert cases[1]["entries"] == [{"body": "opened by hand",
                                    "url": "https://hackclub.slack.com/archives/C_FIRE/p1760000000000200"}]
    assert cases[1]["has_reports"] is False
    assert cases[2]["entries"] == []


def test_open_cases_query_orders_oldest_first_with_limit():
    assert "WHERE c.resolved_at IS NULL" in open_cases.OPEN_CASES
    assert "ORDER BY c.opened_at, c.id" in open_cases.OPEN_CASES
    assert "WHERE report_index <= %s" in open_cases.CASE_REPORTS


def test_parse_command_queue_requires_case_read():
    assert command.parse_command("queue") == (command.QUEUE, None, None)
    assert command.NEEDED[command.QUEUE] == "case.read"
    assert "/nemo queue" in command.helping.flat({"case.read"})
