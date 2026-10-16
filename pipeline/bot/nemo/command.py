import datetime as dt
import logging
import re

from bot.core import access, audit, richtext, session
from bot.core.formatting import short_end
from bot.nemo import (
    case_actions,
    case_queue,
    channel,
    channelguards,
    memberguards,
    open_cases,
    purge_requests,
    record,
)
from bot.nemo.views import help as helping
from bot.nemo.views import merge, queued, report
from bot.nemo.views import slowmode as slowcard

log = logging.getLogger("bot.nemo")

COMMAND = "/nemo"
LOOKUP = "lookup"
NOTE = "note"
OPEN = "open"
MERGE = "merge"
SHUSH = "shush"
CHANNEL_BAN = "channelban"
UNSHUSH = "unshush"
UNBAN = "unban"
PURGE = "purge"
SLOWMODE = "slowmode"
QUEUE = "queue"
OPEN_RECORD = "open_record"
OFF = "off"

ABOUT_SOMEBODY = (LOOKUP, NOTE, SHUSH, CHANNEL_BAN, UNSHUSH, UNBAN)
MEMBER_VERBS = (*ABOUT_SOMEBODY, OPEN, PURGE)
VERBS = (*ABOUT_SOMEBODY, OPEN, MERGE, PURGE, SLOWMODE, QUEUE)
NEEDS_WORDS = (NOTE, OPEN, SHUSH, CHANNEL_BAN, SLOWMODE)

WHO = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
WHERE = re.compile(r"<#(C[A-Z0-9]+)(?:\|[^>]*)?>")
CASE = re.compile(r"\A#?(\d+)\Z")
MEMBER_ID = re.compile(r"\A[UW][A-Z0-9]{2,}\Z")
LENGTH = re.compile(r"\A(\d{1,6})([mhdw])\Z", re.IGNORECASE)
ON_A_DATE = re.compile(r"\A(\d{4})-(\d{2})-(\d{2})\Z")
COOLDOWN = re.compile(r"\A(\d{1,4})([sm]?)\Z", re.IGNORECASE)
UNITS = {"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}

LONGEST_DAYS = 365
SHORTEST = dt.timedelta(minutes=1)
LONGEST = dt.timedelta(days=LONGEST_DAYS)

SUBJECT_USAGE = {
    LOOKUP: "Name the member: */nemo lookup @member*",
    NOTE: "Name the member: */nemo note @member text*",
    SHUSH: "Name the member: */nemo shush @member 3d reason*",
    CHANNEL_BAN: "Name the member: */nemo channelban @member #channel 3d reason*",
    UNSHUSH: "Name the member: */nemo unshush @member*",
    UNBAN: "Name the member: */nemo unban @member #channel*",
}

TEXT_USAGE = {
    NOTE: "Add the note: */nemo note @member text*",
    OPEN: "Add a summary: */nemo open @member summary*",
    SHUSH: "Add a reason: */nemo shush @member 3d reason*",
    CHANNEL_BAN: "Add a reason: */nemo channelban @member #channel 3d reason*",
    SLOWMODE: "Usage: */nemo slowmode #channel 30s 2h reason* · */nemo slowmode #channel off*",
}

HOW_LONG = (
    "Duration: 30m, 2h, 3d, 2w or a date (2026-10-15), up to "
    f"{LONGEST_DAYS} days. Omit it for no end date: *{{example}}*"
)

DURATION_USAGE = {
    SHUSH: HOW_LONG.format(example="/nemo shush @member 3d reason"),
    CHANNEL_BAN: HOW_LONG.format(example="/nemo channelban @member #channel 3d reason"),
    SLOWMODE: HOW_LONG.format(example="/nemo slowmode #channel 30s 2h reason"),
}

COOLDOWN_USAGE = (
    f"Cooldown: 30s, 2m or seconds, from {slowcard.SHORTEST} to {slowcard.LONGEST}: "
    "*/nemo slowmode #channel 30s reason*"
)
SLOWMODE_REASON_USAGE = "Add a reason: */nemo slowmode #channel 30s reason*"

CHANNEL_USAGE = "Name the channel: */nemo channelban @member #channel 3d reason*"
UNBAN_CHANNEL_USAGE = "Name the channel: */nemo unban @member #channel*"


def parse_command(text):
    text = (text or "").strip()
    if not text:
        return None, None, None

    first, _, remainder = text.partition(" ")
    number = CASE.match(first)
    if number:
        return "case", int(number.group(1)), None

    verb = first.lower()
    if verb not in VERBS:
        return None, None, None

    mention = WHO.search(remainder)
    if not mention:
        user_id, rest = richtext.leading_user_id(remainder) if verb in MEMBER_VERBS else (None, remainder)
        return verb, user_id, re.sub(r"\s+", " ", rest).strip() or None

    who = mention.group(1)
    body = re.sub(r"\s+", " ", remainder[: mention.start()] + " " + remainder[mention.end() :]).strip()
    return verb, (who if MEMBER_ID.match(who) else None), body or None


def end_of_day(on):
    return dt.datetime.combine(on, dt.time(23, 59, 59), dt.timezone.utc)


def is_length(text):
    return bool(LENGTH.match(text) or ON_A_DATE.match(text))


def ends_at(text, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    match = LENGTH.match(text)
    if match:
        length = dt.timedelta(**{UNITS[match.group(2).lower()]: int(match.group(1))})
        if not SHORTEST <= length <= LONGEST:
            return None
        return now + length

    match = ON_A_DATE.match(text)
    if not match:
        return None

    try:
        on = dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    if not now.date() < on <= (now + LONGEST).date():
        return None
    return end_of_day(on)


def for_how_long(body, now=None):
    text = re.sub(r"\s+", " ", body or "").strip()
    first, _, remainder = text.partition(" ")
    if not is_length(first):
        return True, None, text or None
    expires_at = ends_at(first, now)
    return expires_at is not None, expires_at, remainder or None


def cooldown_of(text):
    match = COOLDOWN.match(text or "")
    if not match:
        return None
    seconds = int(match.group(1)) * (60 if match.group(2).lower() == "m" else 1)
    return seconds if slowcard.SHORTEST <= seconds <= slowcard.LONGEST else None


def slowmode_request(body, here, now=None):
    where, rest = in_a_channel(body)
    if where is None:
        where, rest = here, re.sub(r"\s+", " ", body or "").strip()
    if not where or where.startswith("D"):
        return None, TEXT_USAGE[SLOWMODE]

    first, _, remainder = (rest or "").partition(" ")
    if first.lower() == OFF:
        return {"channel_id": where, "off": True}, None
    seconds = cooldown_of(first)
    if seconds is None:
        return None, COOLDOWN_USAGE
    valid, expires_at, why = for_how_long(remainder, now)
    if not valid:
        return None, DURATION_USAGE[SLOWMODE]
    if not why:
        return None, SLOWMODE_REASON_USAGE
    return {"channel_id": where, "off": False, "seconds": seconds, "expires_at": expires_at,
            "reason": why}, None


def apply_slowmode(conn, request, by):
    channel_id = request["channel_id"]
    current = channelguards.slowmode_row(conn, channel_id)
    if request["off"]:
        if current is None:
            return f"No slow mode in <#{channel_id}>"
        channelguards.lift(conn, current["id"], by)
        return f"Slow mode disabled in <#{channel_id}>"

    seconds, expires_at, reason = request["seconds"], request["expires_at"], request["reason"]
    if current:
        channelguards.tune_slowmode(conn, current, seconds, by, reason, expires_at)
        verb = "updated"
    else:
        channelguards.open_slowmode(conn, channel_id, channelguards.CHANNEL_WIDE, seconds, by, reason,
                                    expires_at, notice_wanted=True)
        verb = "enabled"
    return slowcard.confirmation(verb, seconds, expires_at, reason, channel_id)


def in_a_channel(body):
    match = WHERE.search(body or "")
    if not match:
        return None, None

    text = body[: match.start()] + " " + body[match.end() :]
    return match.group(1), re.sub(r"\s+", " ", text).strip() or None


def message_only(text):
    return {
        "text": text,
        "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": text}}],
    }


def bullets(entries):
    return {
        "type": "rich_text",
        "elements": [
            {
                "type": "rich_text_list",
                "style": "bullet",
                "elements": [
                    {"type": "rich_text_section", "elements": richtext.elements(record.line(one))}
                    for one in entries
                ],
            }
        ],
    }


def looked_up(member_record, names=None):
    user_id = member_record["user_id"]
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*<@{user_id}>*  ·  {record.in_force_line(member_record['in_force'])}"},
        },
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": record.counted(member_record["counts"])}],
        },
    ]

    if member_record["entries"]:
        blocks.append({"type": "divider"})
        blocks.append(bullets(member_record["entries"]))
        if member_record["total"] > len(member_record["entries"]):
            blocks.append(
                {
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"showing {len(member_record['entries'])} of {member_record['total']}",
                        }
                    ],
                }
            )
    else:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": "No record"}],
            }
        )

    where = channel.member_url(user_id)
    if where:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": OPEN_RECORD,
                        "text": {"type": "plain_text", "text": "Open in Fire Engine"},
                        "url": where,
                    }
                ],
            }
        )

    return {"text": f"the record of {user_id}", "blocks": blocks}


NEEDED = {
    LOOKUP: "case.read",
    NOTE: "member.note",
    OPEN: "case.open",
    MERGE: "case.resolve",
    SHUSH: "member.guard",
    CHANNEL_BAN: "member.guard",
    UNSHUSH: "member.guard",
    UNBAN: "member.guard",
    SLOWMODE: "channel.guard",
    QUEUE: "case.read",
    "case": "case.read",
}


def already_open(user_id, numbers):
    text = ", ".join(f"*case {one}*" for one in numbers)
    return f"<@{user_id}> already has an open case: {text}. Add to that one instead."


def ending(expires_at):
    return f"until {short_end(expires_at)}" if expires_at else "with no end date"


def shushed(user_id, expires_at, why):
    return f"<@{user_id}> has been shushed {ending(expires_at)}. Reason: {why}"


def already_shushed(user_id):
    return f"<@{user_id}> is already shushed. Lift or extend it in Fire Engine."


def banned(user_id, channel_id, expires_at, why):
    return f"<@{user_id}> has been banned from <#{channel_id}> {ending(expires_at)}. Reason: {why}"


def already_banned(user_id, channel_id):
    return (
        f"<@{user_id}> is already banned from <#{channel_id}>. "
        "Lift or extend it in Fire Engine."
    )


def with_reason(text, why):
    return f"{text}. Reason: {why}" if why else text


def lift_guard(conn, user_id, kind, channel_id, why, by):
    guard = memberguards.active_guard(conn, user_id, kind, channel_id)
    if guard is None or guard["state"] != "live":
        return False
    return memberguards.lift(conn, guard["id"], by, why, kind=kind)


def unshushed(conn, user_id, why, by):
    if not lift_guard(conn, user_id, memberguards.SHUSH, None, why, by):
        return f"<@{user_id}> is not shushed"
    return with_reason(f"<@{user_id}> has been unshushed", why)


def unbanned(conn, user_id, body, by):
    where, why = in_a_channel(body)
    if where is None:
        return UNBAN_CHANNEL_USAGE
    if not lift_guard(conn, user_id, memberguards.CHANNEL_BAN, where, why, by):
        return f"<@{user_id}> is not banned from <#{where}>"
    return with_reason(f"<@{user_id}> has been unbanned from <#{where}>", why)


def opened(case_id, user_id):
    text = f"*case {case_id}* opened"
    return f"{text} about <@{user_id}>" if user_id else text


def case_answer(conn, case_id):
    case = channel.gather(conn, case_id)
    if case:
        return {"text": f"case {case_id}", "blocks": report.build_blocks(case)}
    case = case_queue.gather(conn, case_id)
    if case:
        return {"text": f"case {case_id}", "blocks": queued.build_blocks(case)}
    return message_only(f"There is no case {case_id}.")


def helped(user_id):
    with session() as conn:
        capabilities = {row[0] for row in conn.execute(helping.USER_CAPABILITIES, (user_id,)).fetchall()}
        granters = (
            [row[0] for row in conn.execute(helping.GRANTERS).fetchall()] if not capabilities else []
        )
    return helping.build_view(capabilities, granters)


def chosen(body):
    actions = body.get("actions") or [{}]
    value = str(actions[0].get("value") or "")
    return int(value) if value.isdigit() else 0


def register(app):
    @app.action(OPEN_RECORD)
    def on_open_record(ack):
        ack()

    @app.action(purge_requests.CONFIRM)
    def on_purge_confirm(ack, body, respond):
        ack()
        answer = purge_requests.confirm(chosen(body), (body.get("user") or {}).get("id"))
        respond(replace_original=True, **message_only(answer))

    @app.action(purge_requests.CANCEL)
    def on_purge_cancel(ack, body, respond):
        ack()
        purge_requests.cancel(chosen(body), (body.get("user") or {}).get("id"))
        respond(delete_original=True)

    @app.command(COMMAND)
    def on_nemo(ack, command, respond, client):
        ack()
        verb, target_id, body = parse_command(command.get("text"))
        user_id = command["user_id"]

        if verb is None:
            return respond(**helped(user_id))
        if verb in ABOUT_SOMEBODY and target_id is None:
            return respond(**message_only(SUBJECT_USAGE[verb]))
        if verb in NEEDS_WORDS and not body:
            return respond(**message_only(TEXT_USAGE[verb]))

        with session() as conn:
            needs = purge_requests.needed(target_id) if verb == PURGE else NEEDED[verb]
            allowed, refusal = access.may(conn, user_id, needs)
            if not allowed:
                return respond(**message_only(refusal))

            if verb == MERGE:
                target_case_id, duplicate_ids = merge.parse_case_ids(body)
                cases = case_actions.mergeable(conn, [one for one in (target_case_id, *duplicate_ids) if one])
                client.views_open(
                    trigger_id=command["trigger_id"], view=merge.build_view(cases, target_case_id, duplicate_ids)
                )
                return None

            if verb == LOOKUP:
                answer = looked_up(record.read(conn, target_id))
                audit.record(conn, "member", 0, "looked_up", user_id,
                             after={"user_id": target_id})
            elif verb == NOTE:
                case_actions.member_note(conn, target_id, body, user_id)
                answer = message_only(f"Note added to <@{target_id}>.")
            elif verb == SHUSH:
                valid, expires_at, why = for_how_long(body)
                if not valid:
                    answer = message_only(DURATION_USAGE[SHUSH])
                elif not why:
                    answer = message_only(TEXT_USAGE[SHUSH])
                else:
                    guard_id = memberguards.open_guard(
                        conn, memberguards.SHUSH, target_id, user_id, why,
                        expires_at=expires_at,
                    )
                    answer = message_only(
                        shushed(target_id, expires_at, why) if guard_id
                        else already_shushed(target_id)
                    )
            elif verb == CHANNEL_BAN:
                where, remainder = in_a_channel(body)
                valid, expires_at, why = for_how_long(remainder)
                if where is None:
                    answer = message_only(CHANNEL_USAGE)
                elif not valid:
                    answer = message_only(DURATION_USAGE[CHANNEL_BAN])
                elif not why:
                    answer = message_only(TEXT_USAGE[CHANNEL_BAN])
                else:
                    guard_id = memberguards.open_guard(
                        conn, memberguards.CHANNEL_BAN, target_id, user_id, why,
                        channel_id=where, expires_at=expires_at,
                    )
                    answer = message_only(
                        banned(target_id, where, expires_at, why) if guard_id
                        else already_banned(target_id, where)
                    )
            elif verb == UNSHUSH:
                answer = message_only(unshushed(conn, target_id, body, user_id))
            elif verb == UNBAN:
                answer = message_only(unbanned(conn, target_id, body, user_id))
            elif verb == SLOWMODE:
                request, problem = slowmode_request(body, command.get("channel_id"))
                answer = message_only(problem or apply_slowmode(conn, request, user_id))
            elif verb == PURGE:
                request, problem = purge_requests.requested(
                    target_id, body, command.get("channel_id"))
                answer = (message_only(problem) if problem
                          else purge_requests.proposed(conn, request, user_id))
            elif verb == QUEUE:
                answer = open_cases.build_reply(conn)
            elif verb == OPEN:
                open_case_ids = case_actions.open_about(conn, target_id) if target_id else []
                if open_case_ids:
                    answer = message_only(already_open(target_id, open_case_ids))
                else:
                    case_id = case_actions.open_case(conn, target_id, body, user_id)
                    answer = message_only(opened(case_id, target_id))
            else:
                answer = case_answer(conn, target_id)

        log.info("nemo: %s ran %s on %s", user_id, verb, target_id)
        return respond(**answer)
