import pytest

from bot.nemo import screening

USER_ID = "U1"


class Conn:
    def __init__(self, guard_id=7, fails=False):
        self.guard_id = guard_id
        self.fails = fails
        self.statements = []

    def execute(self, sql, args=None):
        self.statements.append((sql, args))
        return self

    def fetchone(self):
        sql, _ = self.statements[-1]
        if "make_interval" in sql:
            return ("later",)
        return (1,)

    def fetchall(self):
        return []

    def args_for(self, mark):
        return [args for sql, args in self.statements if mark in sql]

    def executed(self, mark):
        return any(mark in sql for sql, _ in self.statements)


def domain_rule(domain="throwaway.example", match_mode="exact", effect="flag", domain_id=3):
    return screening.DomainRule(domain_id, domain, match_mode, effect)


def set_rules(*domains):
    screening._rules[:] = list(domains)
    screening._loaded = True


@pytest.fixture(autouse=True)
def reset_rules():
    set_rules()
    yield
    set_rules()


def outcome_of(conn):
    return conn.args_for("INSERT INTO fd.join_screen")[0][5]


class LogSlack:
    def __init__(self):
        self.posted = []

    def chat_postMessage(self, **kwargs):
        self.posted.append(kwargs)
        return {"ts": "1.1"}


def test_screen_flagged_domain_posts_notice_to_log_channel(monkeypatch):
    set_rules(domain_rule(effect="flag"))
    from bot.nemo import channel
    monkeypatch.setattr(channel, "log_channel", lambda _conn=None: "CHOUSE")
    log_slack = LogSlack()

    screening.screen(Conn(), USER_ID, "kid@throwaway.example", client=log_slack)

    assert log_slack.posted[0]["channel"] == "CHOUSE"
    assert "throwaway.example" in log_slack.posted[0]["text"]
    assert USER_ID in log_slack.posted[0]["text"]


def test_screen_allowed_domain_does_not_post_notice(monkeypatch):
    set_rules(domain_rule())
    from bot.nemo import channel
    monkeypatch.setattr(channel, "log_channel", lambda _conn=None: "CHOUSE")
    log_slack = LogSlack()

    screening.screen(Conn(), USER_ID, "kid@school.example", client=log_slack)
    assert log_slack.posted == []


def test_screen_failing_notice_post_still_records_flagged_outcome(monkeypatch):
    set_rules(domain_rule(effect="flag"))
    from bot.nemo import channel
    monkeypatch.setattr(channel, "log_channel", lambda _conn=None: "CHOUSE")

    class FailingSlack:
        def chat_postMessage(self, **_kwargs):
            raise RuntimeError("channel_not_found")

    conn = Conn()
    assert screening.screen(conn, USER_ID, "kid@throwaway.example",
                            client=FailingSlack())[0] == screening.FLAGGED
    assert outcome_of(conn) == screening.FLAGGED


def test_domain_of_normalizes_email_and_returns_none_for_invalid():
    assert screening.domain_of("Kid@Throwaway.Example ") == "throwaway.example"
    assert screening.domain_of("kid@sub.school.example") == "sub.school.example"
    assert screening.domain_of("nonsense") is None
    assert screening.domain_of("") is None
    assert screening.domain_of(None) is None


def test_screen_without_email_records_no_email_outcome():
    conn = Conn()
    assert screening.screen(conn, USER_ID, None) == (screening.NO_EMAIL, None)
    assert outcome_of(conn) == screening.NO_EMAIL


def test_screen_unlisted_domain_records_allowed_outcome():
    set_rules(domain_rule())
    conn = Conn()

    assert screening.screen(conn, USER_ID, "kid@school.example") == (screening.ALLOWED, None)
    row = conn.args_for("INSERT INTO fd.join_screen")[0]
    assert row[1] == "school.example"
    assert row[5] == screening.ALLOWED


def test_domain_rule_exact_matches_only_same_domain():
    rule = domain_rule(match_mode="exact")
    assert rule.matches("throwaway.example")
    assert not rule.matches("mail.throwaway.example")
    assert not rule.matches("throwaway.example.co")


def test_domain_rule_suffix_matches_subdomains_not_lookalike():
    rule = domain_rule(match_mode="suffix")
    assert rule.matches("throwaway.example")
    assert rule.matches("mail.throwaway.example")
    assert not rule.matches("notthrowaway.example")


def test_screen_flag_rule_records_outcome_without_opening_guard():
    set_rules(domain_rule(effect="flag"))
    conn = Conn()

    assert screening.screen(conn, USER_ID, "kid@throwaway.example") == (screening.FLAGGED, None)
    assert outcome_of(conn) == screening.FLAGGED
    assert not conn.executed("INSERT INTO fd.member_guards")


def test_screen_hold_rule_opens_shush_with_expiry():
    set_rules(domain_rule(effect="hold"))
    conn = Conn()

    outcome, guard_id = screening.screen(conn, USER_ID, "kid@throwaway.example")
    assert (outcome, guard_id) == (screening.SHUSHED, 1)
    guard_args = conn.args_for("INSERT INTO fd.member_guards")[0]
    assert guard_args[0] == "shush"
    assert guard_args[6] is not None, "a shush must say when it ends"


def test_screen_deactivate_rule_opens_deactivation_without_expiry():
    set_rules(domain_rule(effect="deactivate"))
    conn = Conn()

    outcome, _guard = screening.screen(conn, USER_ID, "kid@throwaway.example")
    assert outcome == screening.DEACTIVATED
    guard_args = conn.args_for("INSERT INTO fd.member_guards")[0]
    assert guard_args[0] == "deactivation"
    assert guard_args[6] is None


def test_highest_severity_returns_most_severe_effect():
    set_rules(domain_rule(effect="flag", domain_id=1),
              domain_rule(effect="deactivate", domain_id=2),
              domain_rule(effect="hold", domain_id=3))

    assert screening.highest_severity("throwaway.example").effect == "deactivate"


def test_screen_guard_insert_returning_none_records_failed_outcome():
    set_rules(domain_rule(effect="hold"))

    class NoGuardConn(Conn):
        def fetchone(self):
            sql, _ = self.statements[-1]
            if "INSERT INTO fd.member_guards" in sql:
                return None
            if "make_interval" in sql:
                return ("later",)
            return (1,)

    conn = NoGuardConn()
    outcome, guard_id = screening.screen(conn, USER_ID, "kid@throwaway.example")

    assert (outcome, guard_id) == (screening.FAILED, None)
    assert outcome_of(conn) == screening.FAILED


def test_active_rules_before_load_returns_none():
    screening._loaded = False
    assert screening.active_rules() is None
    assert screening.highest_severity("throwaway.example") is None


def test_insert_join_screen_sql_ignores_conflicting_user_id():
    assert "ON CONFLICT (user_id) DO NOTHING" in screening.INSERT_JOIN_SCREEN


def test_loop_start_blocked_domain_notification_refreshes_screening(monkeypatch):
    import contextlib
    import threading
    from types import SimpleNamespace

    from bot.nemo import loop

    @contextlib.contextmanager
    def session_of():
        yield object()

    listener, refreshed = {}, []
    monkeypatch.setattr(loop, "session", session_of)
    for module in (loop.guards, loop.channelguards, loop.memberguards, loop.automod, loop.responses, loop.categories):
        monkeypatch.setattr(module, "refresh", lambda conn: 0)
    monkeypatch.setattr(loop.screening, "refresh", lambda conn: refreshed.append(1) or 0)
    monkeypatch.setattr(loop.channel, "refresh_channels", lambda conn: None)
    monkeypatch.setattr(loop.purge, "requeue_interrupted", lambda conn: [])
    monkeypatch.setattr(loop.loops, "run_on_wake", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop.loops, "run_on_timer", lambda *args, **kwargs: (lambda: None))
    monkeypatch.setattr(loop.loops, "run_periodically", lambda *args, **kwargs: None)
    monkeypatch.setattr(loop.loops, "start_listener", lambda name, names, on_notify, stopping:
                        listener.update(names=names, on_notify=on_notify))

    loop.start(SimpleNamespace(client=None), threading.Event())
    refreshed.clear()
    listener["on_notify"](loop.BLOCKED_DOMAIN, "")

    assert loop.BLOCKED_DOMAIN == "fd_blocked_domain"
    assert loop.BLOCKED_DOMAIN in listener["names"]
    assert refreshed == [1]


def test_join_watch_source_fetches_profile_and_upserts_member():
    import pathlib

    from bot.nemo.surface import join_watch

    src = pathlib.Path(join_watch.__file__).read_text()
    assert "privileged.profile(" in src, \
        "team_join carries no email, so the profile has to be fetched"
    assert "new_members.upsert_member(conn, full_profile)" in src, "what slack hands back is kept"


def test_privileged_profile_source_uses_admin_credential():
    import pathlib

    from bot.core import privileged

    assert privileged.PROFILE == "users.info"
    source = pathlib.Path(privileged.__file__).read_text()
    profile_source = source.split("def profile(")[1].split("def ")[0]
    assert 'credential="admin"' in profile_source, \
        "the bot token holds users:read, only the admin token holds users:read.email"


def test_profile_proxy_failure_returns_none(monkeypatch):
    from bot.core import privileged

    monkeypatch.setattr(privileged, "proxy", lambda: (_ for _ in ()).throw(RuntimeError("no")))
    assert privileged.profile("U1") is None
    assert privileged.profile(None) is None


def test_join_watch_source_screens_only_new_members():
    import pathlib

    from bot.nemo.surface import join_watch

    src = pathlib.Path(join_watch.__file__).read_text()
    assert "if not is_new:" in src, "a replayed team_join must not screen them twice"
    assert "screening.screen(" in src
