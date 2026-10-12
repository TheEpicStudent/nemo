from contextlib import contextmanager
from datetime import date

from ingest import analytics_pull
from lib.db import RunCounts

DAY = date(2026, 10, 5)
API_ROWS = [
    {"user_id": "UIDLE", "days_active": 0, "messages_posted": 0, "date_last_active": 1700000000},
    {"user_id": "UREAD", "days_active": 1, "messages_posted": 0},
    {"user_id": "UPOST", "days_active": 1, "messages_posted": 4},
]


class Conn:
    def __init__(self):
        self.written = {}

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, args=None):
        return self

    def executemany(self, sql, rows):
        self.written.setdefault(sql, []).extend(rows)

    def commit(self):
        pass


class Client:
    last_num_found = len(API_ROWS)

    def paginate(self, *_, **__):
        yield from API_ROWS


class Proxy:
    @staticmethod
    def for_source(_key):
        return Client()


def pull(monkeypatch):
    recorded_days, settle_calls = [], []

    @contextmanager
    def run(*_, **__):
        yield RunCounts()

    monkeypatch.setattr(analytics_pull, "ingest_run", run)
    monkeypatch.setattr(analytics_pull, "ProxyClient", Proxy)
    monkeypatch.setattr(analytics_pull, "record_day",
                        lambda _conn, source, day, rows: recorded_days.append((source, day, rows)))
    monkeypatch.setattr(analytics_pull.coverage, "claim_slice", lambda *_, **__: object())
    monkeypatch.setattr(analytics_pull.coverage, "settle",
                        lambda *args, **_: settle_calls.append(args[-2:]))
    conn = Conn()
    analytics_pull.pull_member_day(conn, DAY)
    return conn, recorded_days, settle_calls


def test_a_member_who_did_nothing_that_day_gets_no_row(monkeypatch):
    conn, _, _ = pull(monkeypatch)

    user_ids = [row[0] for row in conn.written[analytics_pull.MEMBER_ACTIVITY_SQL]]
    assert user_ids == ["UREAD", "UPOST"]


def test_everybody_slack_sent_still_feeds_the_member_dimension(monkeypatch):
    conn, _, _ = pull(monkeypatch)

    merged = sorted(row[0] for row in conn.written[analytics_pull.MEMBER_DIM_MERGE_SQL])
    assert merged == ["UIDLE", "UPOST", "UREAD"]


def test_the_day_counts_what_slack_sent_not_what_was_stored(monkeypatch):
    _, recorded_days, settle_calls = pull(monkeypatch)

    assert recorded_days == [(analytics_pull.MEMBER_DAY, DAY, len(API_ROWS))], (
        "a day is loaded when every member arrived, idle or not"
    )
    assert settle_calls == [(len(API_ROWS), len(API_ROWS))]
