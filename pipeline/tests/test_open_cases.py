import datetime as dt

import pytest

from bot.nemo import command, open_cases
from bot.nemo.views import open_cases as view

NOW = dt.datetime(2026, 10, 16, 12, 0, tzinfo=dt.UTC)
CASE_URL = "https://fe.example/fd/cases/"
REPORT_URL = "https://hackclub.slack.com/archives/C_FIRE/p1760000000000100"


def case(case_id, category_key=None, hours=3, assignees=(), entries=None, is_report=True):
    return {"case_id": case_id, "category_key": category_key, "opened_at": NOW - dt.timedelta(hours=hours),
            "assignees": list(assignees), "url": f"{CASE_URL}{case_id}",
            "entries": entries if entries is not None else [{"body": "spam in #lounge", "url": REPORT_URL}],
            "is_report": is_report}


def rich_lists(answer):
    return [one for one in answer["blocks"][0]["elements"] if one["type"] == "rich_text_list"]


def test_build_nests_report_links_under_each_case():
    answer = view.build(2, [case(4913, "spam", hours=76), case(4920, assignees=["UMOD", "UTWO"])], {}, now=NOW)

    assert answer["text"] == "Open cases (2)"
    lists = rich_lists(answer)
    assert [one["indent"] for one in lists] == [0, 1, 0, 1]
    first = lists[0]["elements"][0]["elements"]
    assert first[0] == {"type": "link", "url": f"{CASE_URL}4913", "text": "Case 4913", "style": {"bold": True}}
    assert first[1]["text"] == " · Spam, mass pings or invites · 3d 4h ago"
    assert lists[1]["elements"][0]["elements"] == [{"type": "link", "url": REPORT_URL, "text": "spam in #lounge"}]
    second = lists[2]["elements"][0]["elements"]
    assert [one.get("text") or one.get("user_id") for one in second[1:]] == \
        [" · 3h 0m ago · Assigned: ", "UMOD", ", ", "UTWO"]


def test_build_lists_each_report_and_names_empty_ones():
    entries = [{"body": None, "url": REPORT_URL}, {"body": "second report", "url": None}]

    lists = rich_lists(view.build(1, [case(1, entries=entries)], {}, now=NOW))

    assert [line["elements"] for line in lists[1]["elements"]] == [
        [{"type": "link", "url": REPORT_URL, "text": view.REPORT}],
        [{"type": "text", "text": "second report"}],
    ]


def test_build_names_an_empty_case_card():
    lists = rich_lists(view.build(1, [case(1, entries=[{"body": "", "url": REPORT_URL}], is_report=False)], {},
                                  now=NOW))

    assert lists[1]["elements"][0]["elements"][0]["text"] == view.CARD


def test_build_without_entries_has_no_nested_list():
    assert [one["indent"] for one in rich_lists(view.build(1, [case(1, entries=[])], {}, now=NOW))] == [0]


def test_build_shows_the_cap_and_the_fire_engine_link():
    answer = view.build(61, [case(1)], {}, now=NOW, list_url="https://fe.example/fd/cases?view=attention")

    assert answer["blocks"][1] == {"type": "context", "elements": [{"type": "mrkdwn", "text": "showing 1 of 61"}]}
    assert answer["blocks"][2]["elements"][0]["url"] == "https://fe.example/fd/cases?view=attention"


def test_build_with_nothing_open_is_a_bare_title():
    assert view.build(0, [], {}) == {
        "text": view.EMPTY, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": "No open cases"}}],
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
def test_snippet_reads_slack_markup_as_plain_text(body, expected):
    assert view.snippet(body, {"U1": "Ana", "C1": "lounge"}) == expected


def test_mentioned_collects_users_and_channels():
    assert view.mentioned(["<@U2> in <#C1|x>", "<@U1|a> <@U2>", None]) == (["U1", "U2"], ["C1"])


class Conn:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        self.sql = sql
        return self

    def fetchone(self):
        return self.rows[self.sql]

    def fetchall(self):
        return self.rows.get(self.sql, [])


def test_gather_takes_reports_or_falls_back_to_the_case_card(monkeypatch):
    monkeypatch.setattr(open_cases, "case_url", lambda case_id: f"{CASE_URL}{case_id}")
    opened = NOW - dt.timedelta(days=1)
    conn = Conn({
        open_cases.OPEN_COUNT: (30,),
        open_cases.OPEN_CASES: [(1, "spam", opened, None, None, None, ["UMOD"]),
                                (2, None, opened, "C_FIRE", "1760000000.000200", None, []),
                                (3, None, opened, None, None, None, [])],
        open_cases.REPORTS: [(1, "first", "C_FIRE", "1760000000.000100"), (1, "second", "C_FIRE", None)],
        open_cases.OPENINGS: [(2, "opened by hand")],
    })

    total, cases = open_cases.gather(conn)

    assert total == 30
    assert conn.executed[1][1] == (open_cases.LIMIT,)
    assert conn.executed[2][1] == ([1, 2, 3], open_cases.REPORTS_PER_CASE)
    assert cases[0]["entries"] == [{"body": "first", "url": REPORT_URL}, {"body": "second", "url": None}]
    assert cases[0]["is_report"] is True and cases[0]["assignees"] == ["UMOD"]
    assert cases[1]["entries"] == [{"body": "opened by hand",
                                    "url": "https://hackclub.slack.com/archives/C_FIRE/p1760000000000200"}]
    assert cases[1]["is_report"] is False
    assert cases[2]["entries"] == []


def test_open_cases_query_is_oldest_first_and_capped():
    assert "WHERE c.resolved_at IS NULL" in open_cases.OPEN_CASES
    assert "ORDER BY c.opened_at, c.id" in open_cases.OPEN_CASES
    assert "WHERE n <= %s" in open_cases.REPORTS


def test_queue_is_a_case_read_command():
    assert command.parse_command("queue") == (command.QUEUE, None, None)
    assert command.NEEDED[command.QUEUE] == "case.read"
    assert "/nemo queue" in command.helping.flat({"case.read"})
