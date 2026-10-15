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
    screening._watching[:] = list(domains)
    screening._loaded = True


@pytest.fixture(autouse=True)
def clean():
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


def test_a_catch_is_said_in_the_firehouse(monkeypatch):
    set_rules(domain_rule(effect="flag"))
    from bot.nemo import channel
    monkeypatch.setattr(channel, "log_channel", lambda _conn=None: "CHOUSE")
    log_slack = LogSlack()

    screening.screen(Conn(), USER_ID, "kid@throwaway.example", client=log_slack)

    assert log_slack.posted[0]["channel"] == "CHOUSE"
    assert "throwaway.example" in log_slack.posted[0]["text"]
    assert USER_ID in log_slack.posted[0]["text"]


def test_somebody_the_list_lets_in_is_not_announced(monkeypatch):
    set_rules(domain_rule())
    from bot.nemo import channel
    monkeypatch.setattr(channel, "log_channel", lambda _conn=None: "CHOUSE")
    log_slack = LogSlack()

    screening.screen(Conn(), USER_ID, "kid@school.example", client=log_slack)
    assert log_slack.posted == []


def test_a_firehouse_that_will_not_take_it_does_not_lose_the_screen(monkeypatch):
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


def test_an_address_is_read_down_to_its_domain():
    assert screening.domain_of("Kid@Throwaway.Example ") == "throwaway.example"
    assert screening.domain_of("kid@sub.school.example") == "sub.school.example"
    assert screening.domain_of("nonsense") is None
    assert screening.domain_of("") is None
    assert screening.domain_of(None) is None


def test_somebody_with_no_address_is_written_down_rather_than_guessed_at():
    conn = Conn()
    assert screening.screen(conn, USER_ID, None) == (screening.NO_EMAIL, None)
    assert outcome_of(conn) == screening.NO_EMAIL


def test_a_domain_nobody_holds_lets_them_in_and_still_says_so():
    set_rules(domain_rule())
    conn = Conn()

    assert screening.screen(conn, USER_ID, "kid@school.example") == (screening.ALLOWED, None)
    row = conn.args_for("INSERT INTO fd.join_screen")[0]
    assert row[1] == "school.example"
    assert row[5] == screening.ALLOWED


def test_exact_holds_only_that_domain():
    one = domain_rule(match_mode="exact")
    assert one.holds("throwaway.example")
    assert not one.holds("mail.throwaway.example")
    assert not one.holds("throwaway.example.co")


def test_suffix_holds_what_sits_under_it_but_not_a_lookalike():
    one = domain_rule(match_mode="suffix")
    assert one.holds("throwaway.example")
    assert one.holds("mail.throwaway.example")
    assert not one.holds("notthrowaway.example")


def test_a_flagged_domain_is_written_down_and_nothing_else_happens():
    set_rules(domain_rule(effect="flag"))
    conn = Conn()

    assert screening.screen(conn, USER_ID, "kid@throwaway.example") == (screening.FLAGGED, None)
    assert outcome_of(conn) == screening.FLAGGED
    assert not conn.executed("INSERT INTO fd.member_guards")


def test_a_held_domain_opens_a_shush_that_runs_out():
    set_rules(domain_rule(effect="hold"))
    conn = Conn()

    outcome, guard_id = screening.screen(conn, USER_ID, "kid@throwaway.example")
    assert (outcome, guard_id) == (screening.SHUSHED, 1)
    opened = conn.args_for("INSERT INTO fd.member_guards")[0]
    assert opened[0] == "shush"
    assert opened[6] is not None, "a shush must say when it ends"


def test_a_deactivating_domain_opens_a_deactivation_with_no_end():
    set_rules(domain_rule(effect="deactivate"))
    conn = Conn()

    outcome, _guard = screening.screen(conn, USER_ID, "kid@throwaway.example")
    assert outcome == screening.DEACTIVATED
    opened = conn.args_for("INSERT INTO fd.member_guards")[0]
    assert opened[0] == "deactivation"
    assert opened[6] is None


def test_the_worst_effect_wins_when_two_entries_catch_them():
    set_rules(domain_rule(effect="flag", domain_id=1),
              domain_rule(effect="deactivate", domain_id=2),
              domain_rule(effect="hold", domain_id=3))

    assert screening.highest_severity("throwaway.example").effect == "deactivate"


def test_a_guard_that_will_not_open_is_recorded_as_a_failure_not_a_pass():
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


def test_nobody_is_screened_until_the_list_has_been_loaded():
    screening._loaded = False
    assert screening.watching() is None
    assert screening.highest_severity("throwaway.example") is None


def test_one_row_per_member_so_a_replayed_join_cannot_double_up():
    assert "ON CONFLICT (user_id) DO NOTHING" in screening.SCREENED


def test_a_domain_the_web_adds_reaches_the_bot_without_waiting_for_a_sweep():
    import pathlib

    from bot.nemo import loop

    loop_source = pathlib.Path(loop.__file__).read_text()
    assert loop.BLOCKED_DOMAIN == "fd_blocked_domain"
    assert "BLOCKED_DOMAIN)" in loop_source, "the loop must LISTEN for it"
    assert "elif channel_name == BLOCKED_DOMAIN:" in loop_source


def test_the_join_watcher_asks_slack_for_the_address_the_event_leaves_out():
    import pathlib

    from bot.nemo.surface import join_watch

    src = pathlib.Path(join_watch.__file__).read_text()
    assert "privileged.profile(" in src, \
        "team_join carries no email, so the profile has to be fetched"
    assert "new_members.upsert_member(conn, full_profile)" in src, "what slack hands back is kept"


def test_the_profile_is_read_on_the_admin_credential():
    import pathlib

    from bot.core import privileged

    assert privileged.PROFILE == "users.info"
    source = pathlib.Path(privileged.__file__).read_text()
    profile_source = source.split("def profile(")[1].split("def ")[0]
    assert 'credential="admin"' in profile_source, \
        "the bot token holds users:read, only the admin token holds users:read.email"


def test_a_profile_slack_will_not_hand_over_does_not_stop_the_join(monkeypatch):
    from bot.core import privileged

    monkeypatch.setattr(privileged, "proxy", lambda: (_ for _ in ()).throw(RuntimeError("no")))
    assert privileged.profile("U1") is None
    assert privileged.profile(None) is None


def test_the_join_watcher_screens_only_somebody_who_is_new():
    import pathlib

    from bot.nemo.surface import join_watch

    src = pathlib.Path(join_watch.__file__).read_text()
    assert "if not is_new:" in src, "a replayed team_join must not screen them twice"
    assert "screening.screen(" in src
