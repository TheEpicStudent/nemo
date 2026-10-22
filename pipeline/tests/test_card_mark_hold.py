import datetime as dt

from bot.nemo import channel


def test_card_mark_held_open_case_has_no_mark():
    assert channel.card_mark({"resolved_at": None, "mark_held": True}) is None


def test_card_mark_open_case_has_hourglass():
    assert channel.card_mark({"resolved_at": None, "mark_held": False}) == channel.OPEN_MARK


def test_card_mark_closed_case_ignores_the_hold():
    case = {"resolved_at": dt.datetime(2026, 10, 1, tzinfo=dt.UTC), "resolution": "not_conduct",
            "mark_held": True}
    assert channel.card_mark(case) == channel.NOT_CONDUCT_MARK


def test_post_header_on_a_closed_case_without_a_header_posts_nothing():
    case = {"resolved_at": dt.datetime(2026, 10, 1, tzinfo=dt.UTC), "header_ts": None,
            "body": "report body", "case_id": 4}
    assert channel.post_header(None, None, case, "C0BE6N4G2BA", "1760900000.000100") is None


class Slack:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def call(**kwargs):
            self.calls.append(name)
            return {"ok": True, "ts": "9.9"}
        return call


def imported_case(**over):
    case = {"case_id": 5001, "report_id": 10, "forwarded_ts": "1760900000.000100", "card_digest": "mark:",
            "card_channel_id": "C0BE6N4G2BA", "header_ts": None, "resolved_at": None, "resolution": None,
            "imported": True, "mark_held": False, "body": "report body", "url": None}
    case.update(over)
    return case


def test_refresh_card_on_an_imported_case_touches_no_slack(monkeypatch):
    monkeypatch.setattr(channel, "fetch_case", lambda conn, case_id: imported_case())
    slack = Slack()
    assert channel.refresh_card(slack, None, 5001) == "1760900000.000100"
    assert slack.calls == []


def test_refresh_card_on_an_imported_case_without_a_forward_posts_no_card(monkeypatch):
    monkeypatch.setattr(channel, "fetch_case", lambda conn, case_id: imported_case(forwarded_ts=None))
    slack = Slack()
    assert channel.refresh_card(slack, None, 5001) is None
    assert slack.calls == []


def test_reopen_message_on_an_imported_case_posts_nothing(monkeypatch):
    monkeypatch.setattr(channel, "fetch_case", lambda conn, case_id: imported_case())
    slack = Slack()
    assert channel.post_reopen_message(slack, None, 5001, "resolved") is None
    assert slack.calls == []
