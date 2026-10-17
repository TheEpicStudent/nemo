import datetime as dt
import pathlib

import pytest

from ingest import audit_logs_pull as pull
from lib import audit_actions, user_agents, useragent
from lib.proxy_client import ProxyError, stamped

USER_ID = "U1"
APP = "A0BJDDB42N7"
OTHER_ID = "0dc5d1ec-1111-2222-3333-444455556667"


def entry(**over):
    row = {
        "id": "0dc5d1ec-1111-2222-3333-444455556666",
        "date_create": 1790680410,
        "action": "user_login",
        "actor": {"type": "user", "user": {"id": USER_ID, "name": "zev"}},
        "entity": {"type": "user", "user": {"id": USER_ID}},
        "context": {
            "location": {"type": "workspace", "id": "T0266FRGM", "name": "Hack Club"},
            "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0.0.0 Safari/537.36",
            "ip_address": "157.51.215.171",
            "session_id": 12177102026566,
        },
    }
    row.update(over)
    return row


class Counts:
    def __init__(self):
        self.rows_in = 0
        self.rows_rejected = 0


def test_monthly_row_maps_entry_fields_to_columns():
    row = pull.monthly_row(entry(), "audit_logs_tail", frozenset(), {}, None)

    assert str(row[0]) == entry()["id"]
    assert row[1] == dt.datetime.fromtimestamp(1790680410, tz=dt.UTC)
    assert row[2] == "user_login"
    assert row[4:6] == ("user", USER_ID)
    assert row[7:9] == ("user", USER_ID)


def test_is_valid_entry_rejects_invalid_id_date_or_action():
    assert pull.is_valid_entry(entry())
    assert not pull.is_valid_entry(entry(id=""))
    assert not pull.is_valid_entry(entry(id="not-a-uuid"))
    assert not pull.is_valid_entry(entry(date_create=None))
    assert not pull.is_valid_entry(entry(action=""))


def test_view_row_and_monthly_row_flag_events_from_own_app():
    entry_row = entry(action="public_channel_preview",
                 context={"app": {"id": APP, "name": "Nemo"}})

    assert pull.view_row(entry_row, 1, {}, frozenset({APP}))[8] is True
    assert pull.view_row(entry_row, 1, {}, frozenset())[8] is False
    assert pull.monthly_row(entry_row, "k", frozenset({APP}), {}, None)[12] is True
    assert pull.monthly_row(entry(), "k", frozenset({APP}), {}, None)[12] is False


def test_login_row_maps_address_agent_and_session():
    row = pull.login_row(entry())

    assert row[0] == USER_ID
    assert row[2] == "user_login"
    assert row[3] == "157.51.215.171"
    assert row[4] == entry()["context"]["ua"]
    assert row[5] == 12177102026566
    assert str(row[6]) == entry()["id"]


def test_login_row_for_session_actions_with_address_returns_row():
    assert pull.login_row(entry(action="user_login_failed")) is not None
    assert pull.login_row(entry(action="anomaly")) is not None
    assert pull.login_row(entry(action="file_downloaded"))[2] == "file_downloaded"
    assert pull.login_row(entry(action="user_channel_join", details={"type": "JOINED"})) is not None


def test_login_row_for_foreign_session_actions_returns_none():
    chrome = entry()["context"]["ua"]
    app = {"ip_address": "1.2.3.4", "ua": chrome, "app": {"id": APP}}
    script = {"ip_address": "1.2.3.4", "ua": "Slack Ruby Client/2.1.0"}
    no_address = {"ua": chrome}

    assert pull.login_row(entry(action="file_downloaded", context=app)) is None
    assert pull.login_row(entry(action="file_downloaded", context=script)) is None
    assert pull.login_row(entry(action="file_downloaded", context=no_address)) is None
    for kind in ("INVITED", "KICKED"):
        assert pull.login_row(entry(action="user_channel_join", details={"type": kind})) is None
    assert pull.login_row(entry(action="file_downloaded",
                                actor={"type": "app", "app": {"id": APP}})) is None


def test_login_row_for_user_login_from_script_client_returns_row():
    script = {"ip_address": "1.2.3.4", "ua": "Slack Ruby Client/2.1.0"}
    assert pull.login_row(entry(context=script)) is not None


def test_api_client_detects_script_user_agents():
    for ua in ("Slack Ruby Client/2.1.0", "ApiApp/1.0", "Python/3.12 aiohttp/3.9.5",
               "Bun/1.1.38", "python-requests/2.31.0", "slack_bolt/1.18"):
        assert useragent.api_client(ua), ua
    for ua in (entry()["context"]["ua"], "Slack_SSB/4.41.105",
               "Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", None):
        assert not useragent.api_client(ua), ua


def test_login_row_without_actor_user_returns_none():
    assert pull.login_row(entry(actor={"type": "user", "user": {}})) is None
    assert pull.login_row(entry(actor={})) is None


def test_login_row_with_non_numeric_session_sets_session_none():
    row = pull.login_row(entry(context={"session_id": "nonsense", "ip_address": "1.2.3.4"}))
    assert row[5] is None
    assert row[3] == "1.2.3.4"


def test_login_sql_leaves_ip_prefix_to_generated_column():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0144_login_prefix_is_the_network.sql").read_text()
    assert "GENERATED ALWAYS AS" in sql
    assert "network(set_masklen(ip" in sql
    assert "ip_prefix" not in pull.LOGIN_SQL, "the prefix must not be written by hand"


def test_tail_actions_parses_default_set_names_and_explicit_list(monkeypatch):
    monkeypatch.delenv("AUDIT_TAIL_ACTIONS", raising=False)
    assert pull.tail_actions() is None

    monkeypatch.setenv("AUDIT_TAIL_ACTIONS", "login")
    assert pull.tail_actions() == pull.LOGIN_ACTIONS

    monkeypatch.setenv("AUDIT_TAIL_ACTIONS", "login_and_channel")
    assert pull.tail_actions() == pull.LOGIN_AND_CHANNEL_ACTIONS

    monkeypatch.setenv("AUDIT_TAIL_ACTIONS", "Identity")
    assert pull.tail_actions() == pull.IDENTITY_ACTIONS

    monkeypatch.setenv("AUDIT_TAIL_ACTIONS", " user_login , anomaly ")
    assert pull.tail_actions() == ("user_login", "anomaly")


def test_tail_actions_over_cap_truncates_to_max_actions(monkeypatch):
    monkeypatch.setenv("AUDIT_TAIL_ACTIONS", ",".join(f"a{n}" for n in range(60)))
    assert len(pull.tail_actions()) == pull.MAX_ACTIONS


class Refusing:

    def __init__(self, bad="message_deleted"):
        self.bad = bad
        self.requested_actions = []

    def call(self, _method, params, **_over):
        self.requested_actions.append(params.get("action"))
        if self.bad in str(params.get("action", "")).split(","):
            raise refusal()
        return {"entries": [], "response_metadata": {"next_cursor": ""}}

    def paginate(self, _method, params, _key, **_over):
        self.requested_actions.append(params.get("action"))
        if self.bad in str(params.get("action", "")).split(","):
            raise refusal()
        return iter(())


def refusal():
    failure = ProxyError("proxy returned 400: audit 400: Bad Request")
    failure.http_status = 400
    return failure


def test_walk_with_refused_action_retries_without_refused_action(monkeypatch):
    pull.clear_refusals()
    client = Refusing()
    counts = Counts()

    inserted, logins = pull.walk(client, Conn(), "k", counts,
                                 actions=("user_login", "message_deleted", "anomaly"))

    assert (inserted, logins) == (0, 0)
    assert "message_deleted" in pull.refused_actions()
    assert "user_login" not in pull.refused_actions()
    assert client.requested_actions[-1] == "user_login,anomaly", "it walks again without the refused one"
    pull.clear_refusals()


def test_walk_after_refusal_omits_refused_action(monkeypatch):
    pull.clear_refusals()
    client = Refusing()
    pull.walk(client, Conn(), "k", counts_for(), actions=("user_login", "message_deleted"))

    client.requested_actions.clear()
    pull.walk(client, Conn(), "k", counts_for(), actions=("user_login", "message_deleted"))
    assert all("message_deleted" not in str(one) for one in client.requested_actions)
    pull.clear_refusals()


def test_walk_with_every_action_refused_returns_zero_counts():
    pull.clear_refusals()
    client = Refusing(bad="user_login")
    assert pull.walk(client, Conn(), "k", counts_for(), actions=("user_login",)) == (0, 0)
    assert pull.walk(client, Conn(), "k", counts_for(), actions=("user_login",)) == (0, 0)
    pull.clear_refusals()


def test_walk_without_actions_reraises_refusal():
    pull.clear_refusals()

    class AlwaysRefusing:
        def paginate(self, *_args, **_over):
            raise refusal()

    with pytest.raises(ProxyError):
        pull.walk(AlwaysRefusing(), Conn(), "k", counts_for())


def counts_for():
    return Counts()


def test_bounds_returns_one_utc_day():
    start, stop = pull.bounds(dt.date(2026, 9, 29))

    assert start == dt.datetime(2026, 9, 29, tzinfo=dt.UTC)
    assert stop == dt.datetime(2026, 9, 30, tzinfo=dt.UTC)
    assert (stop - start) == dt.timedelta(days=1)


def test_source_key_for_action_sets_returns_distinct_keys():
    assert pull.source_key_for(pull.LOGIN_AND_CHANNEL_ACTIONS) == f"{pull.BACKFILL}:login_and_channel"
    assert pull.source_key_for(pull.LOGIN_ACTIONS) == f"{pull.BACKFILL}:login"
    assert pull.source_key_for(pull.CHANNEL_MEMBERSHIP_ACTIONS) == f"{pull.BACKFILL}:channel_membership"
    assert pull.source_key_for(pull.IDENTITY_ACTIONS) == f"{pull.BACKFILL}:identity"
    assert pull.source_key_for(("user_login",)) == f"{pull.BACKFILL}:custom"
    assert pull.source_key_for(None) == f"{pull.BACKFILL}:all"

    keys = {pull.source_key_for(actions) for actions in pull.ACTION_SETS.values()}
    assert len(keys) == len(pull.ACTION_SETS)


def test_action_sets_stay_within_max_actions_without_duplicates():
    for actions in pull.ACTION_SETS.values():
        assert len(actions) <= pull.MAX_ACTIONS
        assert len(set(actions)) == len(actions)


def test_backfill_default_actions_is_login_and_channel_set():
    import inspect

    actions = inspect.signature(pull.backfill).parameters["actions"].default
    assert actions == pull.LOGIN_AND_CHANNEL_ACTIONS
    assert set(pull.CHANNEL_MEMBERSHIP_ACTIONS) <= set(actions)


def test_identity_actions_extend_login_actions_with_account_changes():
    assert pull.IDENTITY_ACTIONS[:len(pull.LOGIN_ACTIONS)] == pull.LOGIN_ACTIONS
    assert {"user_deactivated", "user_reactivated", "user_profile_updated"} <= set(pull.IDENTITY_ACTIONS)


def test_backfill_set_names_without_env_returns_login_and_channel(monkeypatch):
    monkeypatch.delenv("AUDIT_BACKFILL_SETS", raising=False)

    assert pull.backfill_set_names() == ("login_and_channel",)
    assert pull.backfill_sets() == (pull.LOGIN_AND_CHANNEL_ACTIONS,)


def test_backfill_set_names_preserves_order_and_dedupes(monkeypatch):
    monkeypatch.setenv("AUDIT_BACKFILL_SETS", " Identity , login_and_channel, identity ")

    assert pull.backfill_set_names() == ("identity", "login_and_channel")
    assert pull.backfill_sets() == (pull.IDENTITY_ACTIONS, pull.LOGIN_AND_CHANNEL_ACTIONS)


def test_unknown_backfill_sets_reports_unknown_and_backfill_sets_skips_them(monkeypatch):
    monkeypatch.setenv("AUDIT_BACKFILL_SETS", "identity,missing_set")

    assert pull.unknown_backfill_sets() == ("missing_set",)
    assert pull.backfill_sets() == (pull.IDENTITY_ACTIONS,)


def test_backfill_next_runs_first_set_with_pending_day(monkeypatch):
    monkeypatch.setenv("AUDIT_BACKFILL_SETS", "identity,login_and_channel")
    pending = {pull.source_key_for(pull.LOGIN_AND_CHANNEL_ACTIONS)}
    monkeypatch.setattr(pull, "next_slice",
                        lambda conn, source_key, days: dt.date(2026, 1, 15) if source_key in pending else None)
    calls = []

    def fake_backfill(conn, client=None, actions=None):
        calls.append(actions)
        return 7

    monkeypatch.setattr(pull, "backfill", fake_backfill)

    assert pull.backfill_next(object()) == 7
    assert calls == [pull.LOGIN_AND_CHANNEL_ACTIONS]


def test_backfill_next_with_all_sets_covered_returns_zero(monkeypatch):
    monkeypatch.setenv("AUDIT_BACKFILL_SETS", "identity,login_and_channel")
    monkeypatch.setattr(pull, "next_slice", lambda conn, source_key, days: None)
    calls = []
    monkeypatch.setattr(pull, "backfill", lambda *args, **kwargs: calls.append(args))

    assert pull.backfill_next(object()) == 0
    assert calls == []


def test_unparsed_sql_selects_by_read_at_not_app_null():
    from ingest import useragent_reparse

    assert "FROM slack.user_agent" in useragent_reparse.UNPARSED_SQL
    assert "read_at IS NULL" in useragent_reparse.UNPARSED_SQL
    assert "app IS NULL" not in useragent_reparse.UNPARSED_SQL, (
        "a runtime names no system, so a null os is a finished read, not a pending one; "
        "matching on it re-reads the newest rows forever and never reaches the backlog")
    assert "read_at = now()" in useragent_reparse.UPDATE_PARSED_SQL
    assert "coalesce(%s, app)" in useragent_reparse.UPDATE_PARSED_SQL, "a read must not clear what it has"


def test_user_agents_upsert_sql_sets_read_at():
    assert "read_at" in user_agents.UPSERT_SQL and "now()" in user_agents.UPSERT_SQL, \
        "what the puller parses needs no second pass"


def test_access_logs_pull_stops_at_newest_login_watermark():
    from ingest import access_logs_pull

    src = pathlib.Path(access_logs_pull.__file__).read_text()
    assert "newest_login_at(conn)" in src
    assert "caught_up = True" in src and "break" in src, \
        "slack hands the access log back newest first, so the walk stops at the watermark"
    assert "walk.close()" in src, "the generator is closed so no further page is asked for"
    assert access_logs_pull.OVERLAP_SECONDS >= 1
    assert access_logs_pull.MAX_PAGES >= 1, "a cold start must still be bounded"


def test_pull_overlap_seconds_is_at_least_one():
    assert pull.OVERLAP_SECONDS >= 1


def test_walk_with_start_cursor_passes_oldest_param():
    calls = []

    class Client:
        def paginate(self, _method, params, *_args, **kwargs):
            calls.append((dict(params), kwargs.get("start_cursor")))
            return []

    when = dt.datetime(2026, 9, 29, tzinfo=dt.UTC)
    pull.walk(Client(), Conn(), "k", Counts(), oldest=when, start_cursor="abc")

    params, cursor = calls[0]
    assert cursor == "abc"
    assert params["oldest"] == int(when.timestamp()), \
        "slack pages newest first, so oldest is the stop; without it the walk never ends"


def test_save_and_load_window_cursor_round_trips_window(monkeypatch):
    saved = {}
    monkeypatch.setattr(pull, "save_cursor",
                        lambda _conn, _key, value: saved.update(value=value))

    when = dt.datetime(2026, 9, 29, 12, tzinfo=dt.UTC)
    pull.save_window_cursor(Conn(), pull.TAIL, when, "abc")
    assert saved["value"] == f"{int(when.timestamp())}|abc"

    monkeypatch.setattr(pull, "get_cursor", lambda _conn, _key: saved["value"])
    cursor, window = pull.load_window_cursor(Conn(), pull.TAIL)
    assert cursor == "abc"
    assert window == when, "an interrupted walk resumes on its own window, not a fresh one"


def test_load_window_cursor_without_window_mark_returns_none_pair(monkeypatch):
    monkeypatch.setattr(pull, "get_cursor", lambda _conn, _key: "bare-cursor-no-mark")
    assert pull.load_window_cursor(Conn(), pull.TAIL) == (None, None)

    monkeypatch.setattr(pull, "get_cursor", lambda _conn, _key: "")
    assert pull.load_window_cursor(Conn(), pull.TAIL) == (None, None)


def test_tail_with_refused_cursor_clears_saved_cursor(monkeypatch):
    import contextlib

    cursor_saves = []
    monkeypatch.setattr(pull, "get_cursor", lambda _conn, _key: "1790575062|stale")
    monkeypatch.setattr(pull, "save_cursor",
                        lambda _conn, key, value: cursor_saves.append((key, value)))
    monkeypatch.setattr(pull, "watermark", lambda _conn: None)

    @contextlib.contextmanager
    def fake_ingest_run(*_args, **_kwargs):
        yield Counts()

    monkeypatch.setattr(pull, "ingest_run", fake_ingest_run)

    def refusing_walk(*_args, **_kwargs):
        raise stamped(ProxyError("audit 400: refused"), 400, False)

    monkeypatch.setattr(pull, "walk", refusing_walk)

    with pytest.raises(ProxyError):
        pull.tail(Conn(), client=object())

    assert (pull.TAIL, "") in cursor_saves, "a wedged cursor must not survive the failed run"


def test_tail_with_non_refusal_failure_preserves_saved_cursor(monkeypatch):
    import contextlib

    cursor_saves = []
    monkeypatch.setattr(pull, "get_cursor", lambda _conn, _key: "1790575062|good")
    monkeypatch.setattr(pull, "save_cursor",
                        lambda _conn, key, value: cursor_saves.append((key, value)))
    monkeypatch.setattr(pull, "watermark", lambda _conn: None)

    @contextlib.contextmanager
    def fake_ingest_run(*_args, **_kwargs):
        yield Counts()

    monkeypatch.setattr(pull, "ingest_run", fake_ingest_run)

    def failing_walk(*_args, **_kwargs):
        raise stamped(ProxyError("audit 500: slack fell over"), 500, False)

    monkeypatch.setattr(pull, "walk", failing_walk)

    with pytest.raises(ProxyError):
        pull.tail(Conn(), client=object())

    assert cursor_saves == [], "a passing cursor must survive a wobble at slack's end"


class Conn:
    def __init__(self):
        self.executed = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def executemany(self, sql, rows, returning=False):
        self.executed.append((sql, rows))
        self.returned = [row[0] for row in rows if returning and row[0] not in self.existing_ids]

    existing_ids = frozenset()
    returned = ()

    def results(self):
        for one in self.returned:
            self.answer = [(one,)]
            yield self
        self.answer = []

    def commit(self):
        pass

    def fetchone(self):
        return (0,)

    answer = ()

    def fetchall(self):
        return list(self.answer)

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


def test_insert_rows_writes_event_login_event_and_session_rows():
    conn, counts = Conn(), Counts()
    logout_entry = entry(id=OTHER_ID, action="user_logout", date_create=entry()["date_create"] + 60)
    inserted, logins = pull.insert_rows(conn, [entry(), logout_entry], "audit_logs_tail", frozenset(), counts)

    assert (inserted, logins) == (2, 2)
    assert counts.rows_in == 2
    assert len(conn.args_for("INSERT INTO slack.audit_event")[0]) == 2
    [hour] = conn.args_for("INSERT INTO fd.login_event")[0]
    assert hour[6:] == (2, 1, 0, 0, 2)
    assert conn.args_for("INSERT INTO fd.login_session")[0] == [(SESSION, USER_ID, pull.stamp(entry()["date_create"]))]


def test_insert_rows_with_existing_event_writes_no_login_event():
    conn, counts = Conn(), Counts()
    conn.existing_ids = frozenset({pull.event_uuid(entry()["id"])})

    pull.insert_rows(conn, [entry()], "audit_logs_tail", frozenset(), counts)

    assert conn.args_for("INSERT INTO fd.login_event") == []


def test_hourly_groups_rows_by_member_address_agent_and_hour():
    at = dt.datetime(2026, 9, 1, 12, 10, tzinfo=dt.UTC)
    ua = entry()["context"]["ua"]
    agents = {user_agents.digest(ua): 7}

    def row(minute, action="file_downloaded", ip="1.2.3.4", hour=12):
        when = at.replace(hour=hour, minute=minute)
        return (USER_ID, when, action, ip, ua, None, None)

    rows = pull.hourly([row(10, "user_login"), row(10), row(40, "user_login_failed"), row(50, "anomaly"),
                        row(20, ip="5.6.7.8"), row(5, hour=13)], agents)

    assert rows == [
        (USER_ID, at.replace(minute=0), "1.2.3.4", 7, at.replace(minute=10), at.replace(minute=50), 3, 0, 1, 1, 3),
        (USER_ID, at.replace(minute=0), "5.6.7.8", 7, at.replace(minute=20), at.replace(minute=20), 1, 0, 0, 0, 1),
        (USER_ID, at.replace(hour=13, minute=0), "1.2.3.4", 7, at.replace(hour=13, minute=5),
         at.replace(hour=13, minute=5), 1, 0, 0, 0, 1),
    ]


def test_session_rows_dedupes_to_earliest_login_per_session():
    login = pull.login_row(entry())
    repeat_login = pull.login_row(entry(date_create=entry()["date_create"] + 5))
    downloaded = pull.login_row(entry(action="file_downloaded"))

    assert pull.session_rows([repeat_login, login, downloaded]) == [(SESSION, USER_ID, login[1])]


def test_insert_rows_with_failed_login_skips_member_seen():
    conn, counts = Conn(), Counts()
    failed = {"type": "user", "user": {"id": "U2", "name": "nope"}}
    pull.insert_rows(conn, [entry(), entry(id=OTHER_ID, action="user_login_failed", actor=failed)],
                     "audit_logs_tail", frozenset(), counts)

    assert [ids for ids, _ in conn.args_for("INSERT INTO fd.member_seen")] == [[USER_ID]]


def test_insert_sql_uses_on_conflict_clauses():
    assert "ON CONFLICT (id, at) DO NOTHING\nRETURNING id" in pull.MONTHLY_SQL
    assert "ON CONFLICT (id, at) DO NOTHING\nRETURNING id" in pull.VIEW_SQL
    assert "ON CONFLICT (user_id, source, hour, ip, ua_id) DO UPDATE" in pull.LOGIN_SQL
    assert "hits = existing.hits + EXCLUDED.hits" in pull.LOGIN_SQL
    assert "ON CONFLICT (audit_id) DO NOTHING" in pull.CHANNEL_SQL


def test_identity_row_with_actor_email_returns_identity():
    row = pull.identity_row(entry(actor={"type": "user", "user": {
        "id": USER_ID, "name": "Aleksa Lutovac", "email": "kid@throwaway.example"}}))

    assert row[0] == USER_ID
    assert row[1] == "Aleksa Lutovac"
    assert row[2] == "kid@throwaway.example"


def test_identity_row_without_email_returns_none():
    assert pull.identity_row(entry()) is None
    assert pull.identity_row(entry(actor={"type": "user", "user": {"id": USER_ID}})) is None
    assert pull.identity_row(entry(actor={"type": "app", "app": {"id": "A1"}})) is None


def test_identity_sql_coalesces_email_and_skips_purged():
    assert "coalesce(fd.member_identity.email, EXCLUDED.email)" in pull.IDENTITY_SQL
    assert "purged_at IS NULL" in pull.IDENTITY_SQL, "a purged identity must stay purged"
    assert "EXISTS (SELECT 1 FROM fd.member" in pull.IDENTITY_SQL


def test_insert_rows_with_repeated_member_writes_one_identity_row():
    conn, counts = Conn(), Counts()
    actor = {"type": "user", "user": {"id": USER_ID, "name": "Zev", "email": "z@throwaway.example"}}
    pull.insert_rows(conn, [entry(actor=actor), entry(id="b", actor=actor), entry(id="c", actor=actor)],
              "audit_logs_tail", frozenset(), counts)

    assert len(conn.args_for("INSERT INTO fd.member_identity")[0]) == 1


CHANNEL_ENTITY = {"type": "channel", "channel": {"id": "C1", "name": "lounge", "privacy": "public"}}


def joined(**over):
    row = {"action": "user_channel_join", "entity": CHANNEL_ENTITY, "details": {"is_workflow": False}}
    row.update(over)
    return entry(**row)


def test_channel_row_for_join_maps_channel_fields():
    row = pull.channel_row(joined())

    assert row[2] == USER_ID
    assert row[3] == "C1"
    assert row[4] == "lounge"
    assert row[5] == "public"
    assert row[6] == pull.JOINED
    assert row[7] is False


def test_channel_row_for_leave_sets_departed_and_non_channel_action_returns_none():
    assert pull.channel_row(joined(action="user_channel_leave"))[6] == pull.DEPARTED
    assert pull.channel_row(joined(action="user_login")) is None


def test_channel_row_for_workflow_join_sets_is_workflow():
    assert pull.channel_row(joined(details={"is_workflow": True}))[7] is True


def test_channel_row_without_member_or_channel_is_none():
    assert pull.channel_row(joined(actor={})) is None
    assert pull.channel_row(joined(entity={"type": "channel", "channel": {}})) is None
    assert pull.channel_row(joined(entity={})) is None
    assert pull.channel_row(joined(date_create=None)) is None


def test_insert_rows_projects_channel_joins_with_events():
    conn, counts = Conn(), Counts()
    pull.insert_rows(conn, [joined(), joined(id=OTHER_ID, action="user_channel_leave"), entry()],
              "audit_logs_tail", frozenset(), counts)

    channel_rows = conn.args_for("INSERT INTO fd.member_channel_join")[0]
    assert len(channel_rows) == 2
    assert {one[6] for one in channel_rows} == {pull.JOINED, pull.DEPARTED}


def test_member_channel_join_migration_backfills_audit_events_and_indexes_channel_time():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0148_member_channel_joins.sql").read_text()
    assert "FROM slack.audit_event" in sql, "the history already landed must be projected too"
    assert "ON fd.member_channel_join (channel_id, at DESC)" in sql, "fan-out is read by channel and time"


def test_channel_rename_migration_renames_index_and_trigger_variable():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0234_rename_room_to_channel.sql").read_text()
    assert "RENAME TO member_channel_join_channel_idx" in sql
    assert "CREATE OR REPLACE FUNCTION fd.channel_guard_allow_changed()" in sql
    assert "room" not in sql.split("RENAME TO", 1)[1]


@pytest.mark.parametrize(("agent", "app", "system"), [
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/141.0.0.0 Safari/537.36",
     "Chrome 141.0.0.0", "Windows 10 or 11"),
    ("slack/26.09.41.0.90016209 (samsung SM-A235F; Android 14; store com.android.vending)",
     "Slack Android 26.09.41.0.90016209", "Android 14"),
    ("Python/3.13.15 slackclient/3.43.0 Linux/4.19.0-gvisor", "Slack SDK", "Linux"),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Slack_SSB/4.45.69 Electron/32.2.5",
     "Slack Desktop 4.45.69", "macOS 10.15.7"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_2 like Mac OS X) Version/18.2 Safari/604.1",
     "Safari 18.2", "iOS 18.2"),
    ("com.tinyspeck.chatlyio/26.09.20 (iPhone; iOS 26.6.2; Scale/3.00)",
     "Slack iOS 26.09.20", "iOS 26.6.2"),
    ("com.tinyspeck.chatlyio.NotificationService/26.09.30 (iPhone; iOS 27.0; Scale/3.00)",
     "Slack iOS 26.09.30", "iOS 27.0"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 26_4_2 like Mac OS X) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) CriOS/154.0.8037.55 Mobile/15E148 Safari/604.1",
     "Chrome 154.0.8037.55", "iOS 26.4.2"),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) FxiOS/127.0 Mobile Safari/605.1",
     "Firefox 127.0", "iOS 17.5"),
])
def test_useragent_parse_returns_app_and_os(agent, app, system):
    parsed = useragent.parse(agent)
    assert parsed["ua_app"] == app
    assert parsed["ua_os"] == system


def test_useragent_parse_unrecognised_string_returns_none_fields():
    assert useragent.parse("") == {"ua": None, "ua_app": None, "ua_os": None}
    assert useragent.parse("something else entirely")["ua_app"] is None


def test_useragent_parse_long_string_preserves_full_ua():
    agent = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) " + "Padding/1.0 " * 60 + "End/1"
    assert len(agent) > 700
    assert useragent.parse(agent)["ua"] == agent, "the raw agent string is never cut short"


def test_useragent_parse_preserves_full_version():
    parsed = useragent.parse("Mozilla/5.0 (Windows NT 10.0) Chrome/154.0.8037.55 Safari/537.36")
    assert parsed["ua_app"] == "Chrome 154.0.8037.55"
    assert not hasattr(useragent, "major"), "nothing should be rounding a version down"
    assert not hasattr(useragent, "short"), "nothing should be cutting a string short"


def test_useragent_parse_distinguishes_slack_ios_from_phone_browser():
    ios_agent = useragent.parse("com.tinyspeck.chatlyio/26.09.20 (iPhone; iOS 26.6.2; Scale/3.00)")
    browser = useragent.parse(
        "Mozilla/5.0 (iPhone; CPU iPhone OS 26_4_2 like Mac OS X) CriOS/154.0.8037.55 Safari/604.1")

    assert ios_agent["ua_app"].startswith("Slack iOS")
    assert browser["ua_app"].startswith("Chrome")
    assert ios_agent["ua_os"] == "iOS 26.6.2"
    assert browser["ua_os"] == "iOS 26.4.2"


def test_unparsed_sql_selects_unread_rows_and_migration_adds_unread_index():
    from ingest import useragent_reparse

    assert "WHERE read_at IS NULL" in useragent_reparse.UNPARSED_SQL

    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
            / "0193_login_event_by_hour.sql").read_text()
    assert "user_agent_unread_idx ON slack.user_agent (id) WHERE read_at IS NULL" in sql, \
        "the sweep must be free once it has drained"


class Owners(Conn):
    def __init__(self, owners=()):
        super().__init__()
        self.owners = list(owners)
        self.answer = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        if sql == pull.OWNERS_SQL:
            self.answer = self.owners
        return self

    def fetchall(self):
        return self.answer


SESSION = 12177102026566


def test_own_sessions_drops_actions_from_other_member_session():
    downloaded = pull.login_row(entry(action="file_downloaded"))

    assert pull.own_sessions(Owners(owners=[(SESSION, "U9")]), [downloaded]) == []
    assert pull.own_sessions(Owners(owners=[(SESSION, USER_ID)]), [downloaded]) == [downloaded]
    assert pull.own_sessions(Owners(), [downloaded]) == [downloaded]


def test_own_sessions_resolves_owner_from_login_in_same_batch():
    other = {"type": "user", "user": {"id": "U9", "name": "other"}}
    login = pull.login_row(entry(actor=other))
    downloaded = pull.login_row(entry(action="file_downloaded"))

    assert pull.own_sessions(Owners(), [login, downloaded]) == [login]


def test_login_row_with_redacted_address_sets_address_none():
    redacted = {"ip_address": "redacted", "ua": entry()["context"]["ua"]}

    assert pull.login_row(entry(action="file_downloaded", context=redacted)) is None
    login = pull.login_row(entry(context=redacted))
    assert login is not None and login[3] is None


def test_address_normalizes_valid_and_returns_none_for_invalid():
    assert pull.address(" 157.51.215.171 ") == "157.51.215.171"
    assert pull.address("2001:DB8::1") == "2001:db8::1"
    assert pull.address("redacted") is None
    assert pull.address("") is None
    assert pull.address(None) is None


EVENT_ID = "0dc5d1ec-1111-2222-3333-444455556666"


class Shape(Conn):
    def __init__(self, codes=(), agents=()):
        super().__init__()
        self.codes = list(codes)
        self.agents = list(agents)
        self.answer = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        self.answer = {pull.VIEW_CODES_SQL: self.codes, user_agents.IDS_SQL: self.agents}.get(sql, [])
        return self

    def fetchall(self):
        return self.answer


def test_monthly_row_maps_typed_columns_and_category():
    actor = {"type": "user", "user": {"id": USER_ID, "name": "zev", "email": "Zev@Example.COM"}}
    entity = {"type": "channel", "channel": {"id": "C0APH2MMHH7", "name": "lounge"}}
    agent = entry()["context"]["ua"]
    row = pull.monthly_row(entry(action="user_channel_join", actor=actor, entity=entity), "audit_logs_tail",
                           frozenset(), {user_agents.digest(agent): 7}, None)

    assert str(row[0]) == EVENT_ID
    assert row[2:4] == ("user_channel_join", "channels")
    assert row[6] == "zev@example.com"
    assert row[10] == "C0APH2MMHH7"
    assert row[13] == "157.51.215.171"
    assert row[14] == 7
    assert row[15] == 12177102026566


def test_monthly_row_and_view_row_with_non_uuid_id_return_none():
    assert pull.monthly_row(entry(id="not-a-uuid"), "k", frozenset(), {}, None) is None
    assert pull.view_row(entry(id="not-a-uuid"), 3, {}, frozenset()) is None


def test_monthly_row_with_redacted_address_sets_ip_none():
    row = pull.monthly_row(entry(context={"ip_address": "redacted"}), "k", frozenset(), {}, None)
    assert row[13] is None


def test_channel_of_reads_channel_from_each_entity_type():
    assert pull.channel_of(entry(entity={"type": "channel", "channel": {"id": "C1"}})) == "C1"
    assert pull.channel_of(entry(entity={"type": "message", "message": {"channel": "C2"}})) == "C2"
    assert pull.channel_of(entry(entity={"type": "huddle", "huddle": {"channel_id": "C3"}})) == "C3"
    assert pull.channel_of(entry(entity={"type": "user", "user": {"id": "U1"}})) is None


def test_write_new_shape_routes_view_codes_to_audit_view_and_others_to_audit_event():
    agent = entry()["context"]["ua"]
    conn = Shape(codes=[("file_downloaded", 3)], agents=[(user_agents.digest(agent), 7)])
    downloaded = entry(id="0dc5d1ec-1111-2222-3333-444455556667", action="file_downloaded",
                       entity={"type": "file", "file": {"id": "F123"}})

    inserted_ids, agents = pull.write_new_shape(conn, [entry(), downloaded], "audit_logs_tail", frozenset())

    assert inserted_ids == {pull.event_uuid(entry()["id"]), pull.event_uuid(downloaded["id"])}
    assert agents == {user_agents.digest(agent): 7}

    [view] = conn.args_for("INSERT INTO slack.audit_view")
    assert view[0][2:5] == (3, USER_ID, "F123")
    assert view[0][6] == 7
    [monthly] = conn.args_for("INSERT INTO slack.audit_event")
    assert monthly[0][2] == "user_login"
    [ensure] = conn.args_for("slack.ensure_months")
    assert ensure["first"].day == 1 and ensure["ahead"] == pull.MONTHS_AHEAD


def test_insert_rows_with_non_uuid_entry_counts_rejected_and_skips_insert():
    conn, counts = Conn(), Counts()

    inserted, _ = pull.insert_rows(conn, [entry(), entry(id="b")], "audit_logs_tail", frozenset(), counts)

    assert inserted == 1
    assert counts.rows_rejected == 1
    assert len(conn.args_for("INSERT INTO slack.audit_event")[0]) == 1


def test_login_event_by_hour_migration_aggregates_hourly_with_unique_key():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
           / "0193_login_event_by_hour.sql").read_text()
    assert "date_trunc('hour', e.at, 'UTC')" in sql
    assert "min(e.at), max(e.at), count(*)," in sql
    assert "(user_id, source, hour, ip, ua_id) NULLS NOT DISTINCT" in sql
    assert "WHERE session_id IS NOT NULL AND action = 'user_login'" in sql


def test_audit_months_migration_defines_security_definer_for_audit_tables_only():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
           / "0191_audit_months_run_as_owner.sql").read_text()
    assert "SECURITY DEFINER" in sql and "SET search_path = slack, pg_temp" in sql
    assert "parent NOT IN ('slack.audit_event_monthly'::regclass, 'slack.audit_view'::regclass)" in sql
    assert "FROM PUBLIC" in sql


def test_move_audit_events_migration_copies_rows_before_dropping_and_renaming():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
           / "0192_move_audit_events.sql").read_text()
    before_drop, after_drop = sql.split("DROP TABLE slack.audit_event;")
    assert "INSERT INTO slack.audit_event_monthly" in before_drop and "INSERT INTO slack.audit_view" in before_drop
    assert "ALTER TABLE slack.audit_event_monthly RENAME TO audit_event;" in after_drop
    assert "parent NOT IN ('slack.audit_event'::regclass, 'slack.audit_view'::regclass)" in after_drop
    assert "SECURITY DEFINER" in after_drop


NOT_STORED_ACTIONS = frozenset({"access_log_sign_in"})


def test_move_audit_events_migration_includes_category_for_every_catalogued_action():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
           / "0192_move_audit_events.sql").read_text()
    for action, definition in audit_actions.catalogue()["actions"].items():
        if action in NOT_STORED_ACTIONS:
            continue
        assert f"('{action}', '{definition['category']}')" in sql
