USER_CAPABILITIES = "SELECT capability FROM app.effective_capability WHERE user_id = %s"

GRANTERS = """
SELECT user_id FROM app.effective_capability WHERE capability = 'access.grant'
ORDER BY user_id
"""

OPENING = (
    "*Nemo* keeps the Fire Department's cases, and this is all of it from Slack. "
    "Only what you hold is listed."
)

NOTHING = (
    "You hold nothing in the Fire Department yet, so there is nothing here to run. "
    "Ask {who} for a grant."
)

NOBODY = (
    "You hold nothing in the Fire Department yet, so there is nothing here to run. "
    "Ask a community manager for a grant."
)

LOOKING = (
    "Looking things up",
    (
        ("case.read", "/nemo lookup @somebody", "their record: standing, counts, history"),
        ("case.read", "/nemo 3864", "pull that case up here"),
    ),
)

WRITING = (
    "Writing things down",
    (
        ("member.note", "/nemo note @somebody what you found",
         "a standing note that follows them to every case"),
        ("case.open", "/nemo open @somebody what happened",
         "open a case, naming somebody is optional"),
        ("case.resolve", "/nemo merge 23 25", "close 25 as a duplicate of 23"),
    ),
)

GUARDS = (
    "Holding somebody",
    (
        ("member.guard", "/nemo shush @somebody 3d why",
         "a shush with no case behind it, until that date"),
        ("member.guard", "/nemo channelban @somebody #channel 3d why",
         "a channel ban with no case behind it, until that date"),
    ),
)

THREAD = (
    "In a case thread",
    (
        ("case.reply", "?we are looking at it", "goes to the reporter, with your name on it"),
        ("case.reply", "~?we are looking at it", "goes to the reporter, without your name"),
        ("case.read", "!case", "Case link"),
        ("case.open", "!claim", "Assign yourself"),
        ("case.open", "!assign @user", "Assign a user"),
        ("case.open", "!unassign @user", "Unassign a user"),
        ("case.note", "!note <text>", "Case note"),
        ("member.note", "!note @user <text>", "Member note"),
        ("case.resolve", "!resolve", "Resolve and notify the reporter"),
        ("case.chat", "anything else", "stays with the team as case chat"),
    ),
)

CARD = (
    "On a case card",
    (
        ("case.resolve", ":white_check_mark:", "Resolve"),
        ("case.resolve", ":x:", "Resolve as not a conduct matter"),
        ("case.act", ":ban:", "Log action"),
    ),
)

SECTIONS = (LOOKING, WRITING, GUARDS, THREAD, CARD)


def line(command, note):
    return f"> `{command}` · {note}"


def section(title, rows, capabilities):
    lines = [line(command, note) for key, command, note in rows if key in capabilities]
    if not lines:
        return None
    return "*{}*\n{}".format(title, "\n".join(lines))


def words(title, rows, capabilities):
    text = section(title, rows, capabilities)
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}} if text else None


def grant_prompt(granters):
    if not granters:
        return NOBODY
    return NOTHING.format(who=", ".join(f"<@{one}>" for one in granters))


def build_blocks(capabilities, granters=()):
    built = [{"type": "section", "text": {"type": "mrkdwn", "text": OPENING}}]
    visible_sections = [words(title, rows, capabilities) for title, rows in SECTIONS]
    visible_sections = [one for one in visible_sections if one]

    if not visible_sections:
        return [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": grant_prompt(granters)},
            }
        ]

    for one in visible_sections:
        built.append({"type": "divider"})
        built.append(one)
    return built


def flat(capabilities):
    parts = [section(title, rows, capabilities) for title, rows in SECTIONS]
    return "\n\n".join(one for one in parts if one) or OPENING


def build_view(capabilities, granters=()):
    return {"text": flat(capabilities), "blocks": build_blocks(capabilities, granters)}
