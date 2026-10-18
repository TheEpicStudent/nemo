import re

from bot.nemo import channelguards, channels, guard_notices

READONLY = "readonly"
ACCOUNT_AGE = "accountage"
BOT_ALLOW = "botallow"
VERBS = (READONLY, ACCOUNT_AGE, BOT_ALLOW)

KINDS = {
    READONLY: channelguards.READONLY,
    ACCOUNT_AGE: channelguards.ACCOUNT_AGE,
    BOT_ALLOW: channelguards.BOT_ALLOWLIST,
}
LABELS = {READONLY: "Read-only", ACCOUNT_AGE: "New-account age", BOT_ALLOW: "Bot allow list"}

ON = "on"
OFF = "off"
THREADS = "threads"
ADD = {READONLY: "allow", ACCOUNT_AGE: "allow", BOT_ALLOW: "add"}
REMOVE = {READONLY: "disallow", ACCOUNT_AGE: "disallow", BOT_ALLOW: "remove"}

MAX_AGE_DAYS = 365
DAYS_PER_MONTH = 30
SETTING_DEFAULTS = {"threads": False, "min_age_days": 0}
ALLOWED_SHOWN = 20
AGE = re.compile(r"\A(\d{1,4})([dm]?)\Z", re.IGNORECASE)

CHANNEL_USAGE = {
    READONLY: "Name the channel: */nemo readonly #channel on*",
    ACCOUNT_AGE: "Name the channel: */nemo accountage #channel 7d*",
    BOT_ALLOW: "Name the channel: */nemo botallow #channel on*",
}
SUBJECT_USAGE = {
    READONLY: "Name the member: */nemo readonly #channel allow @member*",
    ACCOUNT_AGE: "Name the member: */nemo accountage #channel allow @member*",
    BOT_ALLOW: "Name the bot: */nemo botallow #channel add @bot*",
}
USAGE = {
    READONLY: "Usage: */nemo readonly #channel on [threads]*, *off*, *allow @member* or *disallow @member*",
    ACCOUNT_AGE: "Usage: */nemo accountage #channel 7d* or *3m*, *off*, *allow @member* or *disallow @member*",
    BOT_ALLOW: "Usage: */nemo botallow #channel on*, *off*, *add @bot* or *remove @bot*",
}
DAYS_USAGE = f"Age: 1 to {MAX_AGE_DAYS} days or 1 to {MAX_AGE_DAYS // DAYS_PER_MONTH} months: */nemo accountage #channel 7d* or *3m*"
NOT_INSIDE = "Nemo is not in this channel"


def plural_days(days):
    return f"{days} day" if days == 1 else f"{days} days"


def missing(verb, channel_id):
    return f"No {LABELS[verb].lower()} in <#{channel_id}>"


def unchanged(current, settings):
    return all(current.get(key, SETTING_DEFAULTS[key]) == value for key, value in settings.items())


def inside(client, conn, channel_id, by):
    return channels.is_inside(conn, channel_id) or bool(channels.join(client, conn, channel_id, by=by))


def with_seat(text, client, conn, channel_id, by):
    if inside(client, conn, channel_id, by):
        return text
    return f"{text}. {NOT_INSIDE}"


def detail(verb, settings):
    if verb == READONLY and settings.get("threads") is True:
        return ", threads included"
    return ""


def status(conn, verb, channel_id):
    label = LABELS[verb]
    row = channelguards.live_guard_settings(conn, channel_id, KINDS[verb])
    if row is None:
        return f"{label} off in <#{channel_id}>"

    guard_id, settings = row
    if verb == ACCOUNT_AGE:
        text = f"{label} {plural_days(int(settings.get('min_age_days') or 0))} in <#{channel_id}>"
    else:
        text = f"{label} on in <#{channel_id}>{detail(verb, settings)}"

    rows = channelguards.allowed(conn, guard_id)
    names = [guard_notices.subject_label(one[0], one[1]) for one in rows[:ALLOWED_SHOWN]]
    if len(rows) > ALLOWED_SHOWN:
        names.append(f"{len(rows) - ALLOWED_SHOWN} more")
    return f"{text}, allowed: {', '.join(names)}" if names else text


def open_or_tune(client, conn, verb, channel_id, settings, enabled_text, by):
    kind = KINDS[verb]
    row = channelguards.live_guard_settings(conn, channel_id, kind)
    if row is not None:
        guard_id, current = row
        if unchanged(current, settings):
            return None
        channelguards.tune(conn, guard_id, settings, by)
        return enabled_text

    guard_id = channelguards.open_guard(conn, channel_id, by, kind=kind, settings=settings)
    if guard_id is None:
        return None
    channelguards.restore_allows(conn, guard_id, channel_id, kind, by)
    return with_seat(enabled_text, client, conn, channel_id, by)


def turn_on(client, conn, verb, channel_id, option, by):
    wanted = option.strip().lower()
    if verb == READONLY and wanted not in ("", THREADS):
        return USAGE[verb]
    if verb != READONLY and wanted:
        return USAGE[verb]

    settings = {"threads": wanted == THREADS} if verb == READONLY else {}
    enabled = f"{LABELS[verb]} enabled in <#{channel_id}>{detail(verb, settings)}"
    text = open_or_tune(client, conn, verb, channel_id, settings, enabled, by)
    return text or f"{LABELS[verb]} already on in <#{channel_id}>"


def set_age(client, conn, channel_id, days, by):
    if not 1 <= days <= MAX_AGE_DAYS:
        return DAYS_USAGE
    enabled = f"{LABELS[ACCOUNT_AGE]} set to {plural_days(days)} in <#{channel_id}>"
    text = open_or_tune(client, conn, ACCOUNT_AGE, channel_id, {"min_age_days": days}, enabled, by)
    return text or f"{LABELS[ACCOUNT_AGE]} already {plural_days(days)} in <#{channel_id}>"


def turn_off(conn, verb, channel_id, by):
    row = channelguards.live_guard_settings(conn, channel_id, KINDS[verb])
    if row is None:
        return missing(verb, channel_id)
    channelguards.lift(conn, row[0], by)
    return f"{LABELS[verb]} disabled in <#{channel_id}>"


def add_subject(conn, verb, channel_id, subject_id, by):
    row = channelguards.live_guard_settings(conn, channel_id, KINDS[verb])
    if row is None:
        return missing(verb, channel_id)
    if subject_id is None:
        return SUBJECT_USAGE[verb]

    guard_id = row[0]
    if subject_id in {one[0] for one in channelguards.allowed(conn, guard_id)}:
        where = "on the allow list" if verb == BOT_ALLOW else "allowed"
        return f"<@{subject_id}> already {where} in <#{channel_id}>"

    channelguards.allow(conn, guard_id, subject_id, by)
    if verb == BOT_ALLOW:
        return f"<@{subject_id}> added to the allow list in <#{channel_id}>"
    return f"<@{subject_id}> allowed in <#{channel_id}>"


def remove_subject(conn, verb, channel_id, subject_id, by):
    row = channelguards.live_guard_settings(conn, channel_id, KINDS[verb])
    if row is None:
        return missing(verb, channel_id)
    if subject_id is None:
        return SUBJECT_USAGE[verb]
    if channelguards.disallow(conn, row[0], subject_id, by) is None:
        return f"<@{subject_id}> is not on the allow list in <#{channel_id}>"
    return f"<@{subject_id}> removed from the allow list in <#{channel_id}>"


def run(client, conn, verb, channel_id, text, subject_id, by):
    if not channel_id or channel_id.startswith("D"):
        return CHANNEL_USAGE[verb]

    action, _, option = (text or "").strip().partition(" ")
    action = action.lower()
    if not action:
        return status(conn, verb, channel_id)
    age = AGE.match(action) if verb == ACCOUNT_AGE else None
    if age:
        days = int(age.group(1)) * (DAYS_PER_MONTH if age.group(2).lower() == "m" else 1)
        return set_age(client, conn, channel_id, days, by)
    if action == ON and verb != ACCOUNT_AGE:
        return turn_on(client, conn, verb, channel_id, option, by)
    if action == OFF:
        return turn_off(conn, verb, channel_id, by)
    if action == ADD[verb]:
        return add_subject(conn, verb, channel_id, subject_id, by)
    if action == REMOVE[verb]:
        return remove_subject(conn, verb, channel_id, subject_id, by)
    return USAGE[verb]
