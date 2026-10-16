from contextlib import contextmanager
from datetime import UTC, datetime

import pytest

from ingest import access_logs_pull
from lib import user_agents

FIRST = 1790000000
LAST = 1790003600
CURSOR = 1780000000


class Counts:
    rows_in = 0
    rows_rejected = 0


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.params = None

    def paginate(self, _method, params, _items_key, on_page=None, **_kwargs):
        self.params = params

        def entries():
            item_count = 0
            for page in self.pages:
                yield from page
                item_count += len(page)
                if on_page:
                    on_page("next", item_count)

        return entries()


class FakeConn:
    def __init__(self, oldest=None):
        self.oldest = oldest

    def execute(self, _sql, _params=None):
        return self

    def fetchone(self):
        return (self.oldest,)

    def commit(self):
        pass


def entry(timestamp):
    return {"user_id": "U1", "date_first": timestamp, "date_last": timestamp}


@pytest.fixture
def cursor_state(monkeypatch):
    state = {"cursor": None, "saved": []}

    @contextmanager
    def fake_ingest_run(*_args, **_kwargs):
        yield Counts()

    monkeypatch.setattr(access_logs_pull, "ingest_run", fake_ingest_run)
    monkeypatch.setattr(access_logs_pull, "insert_rows", lambda _conn, logins, _counts: len(logins))
    monkeypatch.setattr(access_logs_pull, "get_cursor",
                        lambda _conn, _key, max_age_hours=None: state["cursor"])
    monkeypatch.setattr(access_logs_pull, "save_cursor",
                        lambda _conn, _key, value: state["saved"].append(value))
    return state


def test_row_for_maps_date_last_to_at_and_date_first_to_first_seen_at():
    row = access_logs_pull.row_for({"user_id": "U1", "date_first": FIRST, "date_last": LAST})

    assert row is not None
    assert row[1] == datetime.fromtimestamp(LAST, tz=UTC)
    assert row[-1] == datetime.fromtimestamp(FIRST, tz=UTC)


def test_row_for_without_date_first_sets_first_seen_at_none():
    row = access_logs_pull.row_for({"user_id": "U1", "date_last": LAST})

    assert row is not None
    assert row[-1] is None


def test_login_event_row_length_matches_row_sql_placeholders():
    row = access_logs_pull.row_for({"user_id": "U1", "date_first": FIRST, "date_last": LAST})

    assert row is not None
    assert access_logs_pull.ROW_SQL.count("%s") == len(access_logs_pull.login_event_row(row, {}))


def test_login_event_row_buckets_date_last_into_utc_hour():
    row = access_logs_pull.row_for({"user_id": "U1", "date_first": FIRST, "date_last": LAST,
                                    "ip": "1.2.3.4", "user_agent": "Mozilla/5.0 agent"})
    row_values = access_logs_pull.login_event_row(row, {user_agents.digest("Mozilla/5.0 agent"): 7})

    last = datetime.fromtimestamp(LAST, tz=UTC)
    assert row_values[1] == last.replace(minute=0, second=0)
    assert row_values[3] == 7
    assert row_values[4:6] == (last, last)


def test_row_sql_upsert_uses_least_first_seen_at():
    sql = access_logs_pull.ROW_SQL

    assert "first_seen_at = least(EXCLUDED.first_seen_at, existing.first_seen_at)" in sql
    assert "existing.isp)\n      IS DISTINCT FROM" in sql


def test_row_sql_increments_hits_when_range_extends():
    assert ("hits = existing.hits + CASE WHEN EXCLUDED.last_at > existing.last_at OR EXCLUDED.first_at < existing.first_at"
            in access_logs_pull.ROW_SQL)


def test_backfill_without_cursor_starts_at_oldest_stored_login(cursor_state):
    client = FakeClient([[entry(FIRST)]])

    access_logs_pull.backfill(FakeConn(datetime.fromtimestamp(LAST, tz=UTC)), client)

    assert client.params == {"before": LAST}


def test_backfill_without_stored_logins_starts_at_now(cursor_state):
    client = FakeClient([])
    now_ts = int(datetime.now(UTC).timestamp())

    access_logs_pull.backfill(FakeConn(), client)

    assert client.params is not None
    assert now_ts <= client.params["before"] <= now_ts + 60


def test_backfill_with_saved_cursor_resumes_from_cursor(cursor_state):
    cursor_state["cursor"] = str(CURSOR)
    client = FakeClient([])

    access_logs_pull.backfill(FakeConn(datetime.fromtimestamp(LAST, tz=UTC)), client)

    assert client.params == {"before": CURSOR}


def test_backfill_saves_oldest_first_seen_cursor_after_each_page(cursor_state):
    cursor_state["cursor"] = str(CURSOR)
    client = FakeClient([[entry(CURSOR - 10), entry(CURSOR - 20)], [entry(CURSOR - 30)]])

    inserted = access_logs_pull.backfill(FakeConn(), client)

    assert inserted == 3
    assert cursor_state["saved"][:2] == [str(CURSOR - 20), str(CURSOR - 30)]
    assert cursor_state["saved"][-1] == access_logs_pull.BACKFILL_COMPLETE


def test_backfill_at_max_pages_saves_cursor_without_complete_marker(cursor_state, monkeypatch):
    monkeypatch.setattr(access_logs_pull, "PAGE", 2)
    monkeypatch.setattr(access_logs_pull, "MAX_PAGES", 1)
    cursor_state["cursor"] = str(CURSOR)
    client = FakeClient([[entry(CURSOR - 10), entry(CURSOR - 20)], [entry(CURSOR - 30)]])

    inserted = access_logs_pull.backfill(FakeConn(), client)

    assert inserted == 2
    assert cursor_state["saved"][-1] == str(CURSOR - 20)
    assert access_logs_pull.BACKFILL_COMPLETE not in cursor_state["saved"]


def test_backfill_with_empty_page_saves_complete_marker(cursor_state):
    cursor_state["cursor"] = str(CURSOR)

    inserted = access_logs_pull.backfill(FakeConn(), FakeClient([[]]))

    assert inserted == 0
    assert cursor_state["saved"] == [access_logs_pull.BACKFILL_COMPLETE]


def test_backfill_when_complete_makes_no_request(cursor_state):
    cursor_state["cursor"] = access_logs_pull.BACKFILL_COMPLETE
    client = FakeClient([[entry(CURSOR)]])

    assert access_logs_pull.backfill(FakeConn(), client) == 0
    assert client.params is None
    assert cursor_state["saved"] == []


def test_next_before_with_entries_at_start_second_steps_back_one_second():
    start = datetime.fromtimestamp(CURSOR, tz=UTC)
    older = datetime.fromtimestamp(CURSOR - 5, tz=UTC)

    assert access_logs_pull.next_before(CURSOR, start) == CURSOR - 1
    assert access_logs_pull.next_before(CURSOR, older) == CURSOR - 5
