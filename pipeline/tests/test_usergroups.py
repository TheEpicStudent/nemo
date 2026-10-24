from contextlib import contextmanager

from slack_sdk.errors import SlackApiError

from bot.nemo import usergroups


class Client:
    def __init__(self, groups=None, error=None):
        self.groups = groups or []
        self.error = error
        self.calls = []

    def usergroups_list(self, **params):
        self.calls.append(params)
        if self.error:
            raise SlackApiError(f"The request failed: {self.error}", {"ok": False, "error": self.error})
        return {"ok": True, "usergroups": self.groups}


class Cursor:
    def __init__(self, executed):
        self.executed = executed

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def executemany(self, sql, rows):
        self.executed.append((sql, list(rows)))


class Conn:
    def __init__(self):
        self.executed = []

    def cursor(self):
        return Cursor(self.executed)


def fake_session(monkeypatch):
    conn = Conn()

    @contextmanager
    def session():
        yield conn

    monkeypatch.setattr(usergroups, "session", session)
    return conn


def test_fetch_with_team_id_passes_team_id_and_include_disabled(monkeypatch):
    monkeypatch.setenv("SLACK_TEAM_ID", "T0266FRGM")
    client = Client()

    usergroups.fetch(client)

    assert client.calls == [{"include_disabled": True, "team_id": "T0266FRGM"}]


def test_refresh_with_groups_upserts_rows_with_handles(monkeypatch):
    monkeypatch.delenv("SLACK_TEAM_ID", raising=False)
    conn = fake_session(monkeypatch)
    client = Client([{"id": "S1", "handle": "fire-department", "name": "Fire Department"},
                     {"id": "S2", "handle": ""}])

    assert usergroups.refresh(client) == 1
    assert conn.executed[0][1] == [("S1", "fire-department", "Fire Department")]
    assert client.calls == [{"include_disabled": True}]


def test_refresh_with_missing_scope_returns_zero_without_writes(monkeypatch):
    conn = fake_session(monkeypatch)

    assert usergroups.refresh(Client(error="missing_scope")) == 0
    assert conn.executed == []
