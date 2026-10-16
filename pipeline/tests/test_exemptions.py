import pytest

from bot.nemo import exemptions, guards

USER_ID = "U1"
OPENER_ID = "UMOD"


class Conn:
    def __init__(self, bot=False, exempt=False):
        self.bot = bot
        self.exempt = exempt
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        sql, _ = self.executed[-1]
        if sql == guards.BOT_MEMBER:
            return (self.bot,)
        if sql == exemptions.EXEMPT:
            return (self.exempt,)
        raise AssertionError(sql)


def test_exempt_sql_covers_admin_owner_roles_and_staff_capability():
    for column in ("m.is_admin", "m.is_owner", "m.is_org_admin", "m.is_org_owner"):
        assert column in exemptions.EXEMPT
    assert "app.holds_capability(%s, %s)" in exemptions.EXEMPT
    assert exemptions.STAFF_CAPABILITY == "case.read"


@pytest.mark.parametrize("exempt", [True, False])
def test_is_exempt_with_user_runs_exempt_query_and_returns_result(exempt):
    conn = Conn(exempt=exempt)

    assert exemptions.is_exempt(conn, USER_ID) is exempt
    assert conn.executed == [(exemptions.EXEMPT, (USER_ID, exemptions.STAFF_CAPABILITY, USER_ID))]


def test_is_exempt_without_user_returns_false_and_runs_no_query():
    conn = Conn(exempt=True)

    assert exemptions.is_exempt(conn, None) is False
    assert conn.executed == []


@pytest.mark.parametrize(("user_id", "bot", "exempt", "expected"), [
    (OPENER_ID, False, False, True),
    (None, False, False, True),
    (USER_ID, True, False, True),
    (USER_ID, False, True, True),
    (USER_ID, False, False, False),
])
def test_guards_exempt_matches_opener_bot_staff_or_missing_user(user_id, bot, exempt, expected):
    assert guards.exempt(Conn(bot=bot, exempt=exempt), user_id, OPENER_ID) is expected
