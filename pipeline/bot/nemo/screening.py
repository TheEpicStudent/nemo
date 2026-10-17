import logging
import threading

log = logging.getLogger("bot.nemo")

EXACT = "exact"
SUFFIX = "suffix"

FLAG = "flag"
HOLD = "hold"
DEACTIVATE = "deactivate"

ALLOWED = "allowed"
FLAGGED = "flagged"
SHUSHED = "held"
DEACTIVATED = "deactivated"
FAILED = "failed"
NO_EMAIL = "no_email"

WORST_FIRST = (DEACTIVATE, HOLD, FLAG)

OUTCOME_FOR_EFFECT = {FLAG: FLAGGED, HOLD: SHUSHED, DEACTIVATE: DEACTIVATED}

SHUSH_DAYS = 7

OUTCOME_NOTICES = {
    FLAGGED: "Email on {domain} flagged",
    SHUSHED: "Email on {domain} shushed",
    DEACTIVATED: "Email on {domain} deactivated",
    FAILED: "Email on {domain} shush or deactivation failed",
}

ACTIVE_DOMAINS = """
SELECT id, domain, match_mode, effect
FROM fd.blocked_domains
WHERE active
ORDER BY id
"""

INSERT_JOIN_SCREEN = """
INSERT INTO fd.join_screen
    (user_id, email_domain, domain_id, matched, effect, outcome, guard_id, detail)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (user_id) DO NOTHING
RETURNING id
"""

_rules = []
_loaded = False
_lock = threading.Lock()


class DomainRule:
    def __init__(self, domain_id, domain, match_mode, effect):
        self.domain_id = domain_id
        self.domain = (domain or "").strip().lower()
        self.match_mode = match_mode
        self.effect = effect

    def matches(self, domain):
        if not self.domain or not domain:
            return False
        if self.match_mode == EXACT:
            return domain == self.domain
        return domain == self.domain or domain.endswith(f".{self.domain}")


def refresh(conn):
    global _loaded
    rules = [DomainRule(*row) for row in conn.execute(ACTIVE_DOMAINS).fetchall()]
    with _lock:
        _rules[:] = rules
        _loaded = True
    return len(rules)


def active_rules():
    with _lock:
        return list(_rules) if _loaded else None


def domain_of(email):
    text = (email or "").strip().lower()
    if "@" not in text:
        return None
    domain = text.rsplit("@", 1)[-1].strip()
    return domain or None


def highest_severity(domain):
    rules = active_rules()
    if not rules or not domain:
        return None

    matches = [one for one in rules if one.matches(domain)]
    if not matches:
        return None
    return min(matches, key=lambda one: WORST_FIRST.index(one.effect))


def record(conn, user_id, domain, rule, outcome, guard_id=None, detail=None):
    return conn.execute(INSERT_JOIN_SCREEN, (
        user_id, domain,
        rule.domain_id if rule else None,
        rule.domain if rule else None,
        rule.effect if rule else None,
        outcome, guard_id, detail,
    )).fetchone()


def post_to_internal_log(client, conn, user_id, domain, outcome):
    if client is None or outcome not in OUTCOME_NOTICES:
        return None

    from bot.nemo import channel

    log_channel_id = channel.log_channel(conn)
    if not log_channel_id:
        return None

    try:
        client.chat_postMessage(
            channel=log_channel_id,
            text=f"<@{user_id}> joined: {OUTCOME_NOTICES[outcome].format(domain=domain)}",
            unfurl_links=False,
        )
    except Exception as failure:  # noqa: BLE001
        log.warning("nemo: could not say that %s was screened: %s", user_id, failure)
        return None
    return log_channel_id


def screen(conn, user_id, email, by="nemo", client=None):
    domain = domain_of(email)
    if domain is None:
        record(conn, user_id, None, None, NO_EMAIL)
        return NO_EMAIL, None

    rule = highest_severity(domain)
    if rule is None:
        record(conn, user_id, domain, None, ALLOWED)
        return ALLOWED, None

    if rule.effect == FLAG:
        record(conn, user_id, domain, rule, FLAGGED)
        log.warning("nemo: %s joined on %s, which is flagged", user_id, domain)
        post_to_internal_log(client, conn, user_id, domain, FLAGGED)
        return FLAGGED, None

    guard_id, error = open_screening_guard(conn, user_id, rule, by)
    if guard_id is None:
        record(conn, user_id, domain, rule, FAILED, detail=error)
        log.warning("nemo: %s joined on %s but the guard would not open: %s",
                    user_id, domain, error)
        post_to_internal_log(client, conn, user_id, domain, FAILED)
        return FAILED, None

    outcome = OUTCOME_FOR_EFFECT[rule.effect]
    record(conn, user_id, domain, rule, outcome, guard_id=guard_id)
    log.warning("nemo: %s joined on %s, %s", user_id, domain, outcome)
    post_to_internal_log(client, conn, user_id, domain, outcome)
    return outcome, guard_id


def open_screening_guard(conn, user_id, rule, by):
    from bot.nemo import memberguards

    kind = memberguards.DEACTIVATION if rule.effect == DEACTIVATE else memberguards.SHUSH
    reason = f"Signup with email on {rule.domain}"
    expires = None if kind == memberguards.DEACTIVATION else shush_expiry(conn)

    try:
        guard_id = memberguards.open_guard(
            conn, kind, user_id, by, reason, expires_at=expires
        )
    except Exception as failure:  # noqa: BLE001
        return None, str(failure)[:500]

    if guard_id is None:
        return None, "Guard already active"
    return guard_id, None


def shush_expiry(conn):
    row = conn.execute(
        "SELECT now() + make_interval(days => %s)", (SHUSH_DAYS,)
    ).fetchone()
    return row[0] if row else None
