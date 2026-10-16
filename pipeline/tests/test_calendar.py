from datetime import date

from lib import calendar


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class Slack:
    def __init__(self, *ends):
        self.ends = list(ends)
        self.calls = 0

    def call(self, method, params):
        self.calls += 1
        end = self.ends[min(self.calls - 1, len(self.ends) - 1)]
        return {"available_date_range": {"start_date": "2024-01-01", "end_date": end}}


def test_available_within_ttl_returns_cached_window():
    clock, slack = Clock(), Slack("2026-09-10", "2026-09-11")
    assert calendar.available(slack, "member", clock)[1] == date(2026, 9, 10)
    clock.advance(calendar.TTL_SECONDS - 1)
    assert calendar.available(slack, "member", clock)[1] == date(2026, 9, 10)
    assert slack.calls == 1


def test_available_after_ttl_refetches_window():
    clock, slack = Clock(), Slack("2026-09-10", "2026-09-11")
    assert calendar.available(slack, "member", clock)[1] == date(2026, 9, 10)
    clock.advance(calendar.TTL_SECONDS + 1)
    assert calendar.available(slack, "member", clock)[1] == date(2026, 9, 11)
    assert slack.calls == 2


def test_available_across_daily_calls_returns_each_new_end_date():
    clock, slack = Clock(), Slack("2026-09-10", "2026-09-11", "2026-09-12")
    dates = []
    for _ in range(3):
        dates.append(calendar.available(slack, "member", clock)[1])
        clock.advance(24 * 3600)
    assert dates == [date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12)]


def test_available_with_different_kinds_fetches_each_window():
    clock, slack = Clock(), Slack("2026-09-10")
    calendar.available(slack, "member", clock)
    calendar.available(slack, "channel", clock)
    assert slack.calls == 2


def test_clear_drops_cached_window():
    clock, slack = Clock(), Slack("2026-09-10", "2026-09-11")
    assert calendar.available(slack, "member", clock)[1] == date(2026, 9, 10)
    calendar.clear()
    assert calendar.available(slack, "member", clock)[1] == date(2026, 9, 11)
