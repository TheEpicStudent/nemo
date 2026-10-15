import datetime as dt
import logging
import re

from bot.core import access, audit, richtext, session
from bot.core.formatting import short_date
from bot.nemo import case_actions, case_queue, channel, memberguards, purge_requests, record
from bot.nemo.views import help as helping
from bot.nemo.views import merge, queued, report

log = logging.getLogger("bot.nemo")

COMMAND = "/nemo"
LOOKUP = "lookup"
NOTE = "note"
OPEN = "open"
MERGE = "merge"
SHUSH = "shush"
CHANNEL_BAN = "channelban"
PURGE = "purge"
OPEN_RECORD = "open_record"

ABOUT_SOMEBODY = (LOOKUP, NOTE, SHUSH, CHANNEL_BAN)
VERBS = (*ABOUT_SOMEBODY, OPEN, MERGE, PURGE)
NEEDS_WORDS = (NOTE, OPEN, SHUSH, CHANNEL_BAN)

WHO = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
WHERE = re.compile(r"<#(C[A-Z0-9]+)(?:\|[^>]*)?>")
CASE = re.compile(r"\A#?(\d+)\Z")
MEMBER_ID = re.compile(r"\A[UW][A-Z0-9]{2,}\Z")
FOR_A_WHILE = re.compile(r"\A(\d{1,3})([dw])\Z", re.IGNORECASE)
ON_A_DATE = re.compile(r"\A(\d{4})-(\d{2})-(\d{2})\Z")

LONGEST_DAYS = 365

SUBJECT_USAGE = {
    LOOKUP: "Name the member: */nemo lookup @member*",
    NOTE: "Name the member: */nemo note @member text*",
    SHUSH: "Name the member: */nemo shush @member 3d reason*",
    CHANNEL_BAN: "Name the member: */nemo channelban @member #channel 3d reason*",
}

TEXT_USAGE = {
    NOTE: "Add the note: */nemo note @member text*",
    OPEN: "Add a summary: */nemo open @member summary*",
    SHUSH: "Add a duration and reason: */nemo shush @member 3d reason*",
    CHANNEL_BAN: "Add a duration and reason: */nemo channelban @member #channel 3d reason*",
}

HOW_LONG = (
    "Put the duration first: *{example}*. "
    f"Use days (3d), weeks (2w) or a date (2026-10-15), up to {LONGEST_DAYS} days."
)

DURATION_USAGE = {
    SHUSH: HOW_LONG.format(example="/nemo shush @member 3d reason"),
    CHANNEL_BAN: HOW_LONG.format(example="/nemo channelban @member #channel 3d reason"),
}

CHANNEL_USAGE = "Name the channel: */nemo channelban @member #channel 3d reason*"


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
        return verb, None, re.sub(r"\s+", " ", remainder).strip() or None

    who = mention.group(1)
    body = re.sub(r"\s+", " ", remainder[: mention.start()] + " " + remainder[mention.end() :]).strip()
    return verb, (who if MEMBER_ID.match(who) else None), body or None


def ends_on(text):
    match = FOR_A_WHILE.match(text)
    if match:
        days = int(match.group(1)) * (7 if match.group(2).lower() == "w" else 1)
        if not 1 <= days <= LONGEST_DAYS:
            return None
        return dt.date.today() + dt.timedelta(days=days)

    match = ON_A_DATE.match(text)
    if not match:
        return None

    try:
        on = dt.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None
    return on if on > dt.date.today() else None


def for_how_long(body):
    first, _, remainder = (body or "").partition(" ")
    on = ends_on(first)
    if on is None:
        return None, None
    return on, re.sub(r"\s+", " ", remainder).strip() or None


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
    "case": "case.read",
}


def already_open(user_id, numbers):
    text = ", ".join(f"*case {one}*" for one in numbers)
    return f"<@{user_id}> already has an open case: {text}. Add to that one instead."


def shushed(user_id, on):
    return (
        f"<@{user_id}> is shushed until {short_date(on)}, with no case. "
        "Log it on a case if there is one."
    )


def already_shushed(user_id):
    return f"<@{user_id}> is already shushed. Lift or extend it in Fire Engine."


def banned(user_id, channel_id, on):
    return (
        f"<@{user_id}> is banned from <#{channel_id}> "
        f"until {short_date(on)}, with no case. "
        "Log it on a case if there is one."
    )


def already_banned(user_id, channel_id):
    return (
        f"<@{user_id}> is already banned from <#{channel_id}>. "
        "Lift or extend it in Fire Engine."
    )


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
                on, why = for_how_long(body)
                if on is None:
                    answer = message_only(DURATION_USAGE[SHUSH])
                elif not why:
                    answer = message_only(TEXT_USAGE[SHUSH])
                else:
                    guard_id = memberguards.open_guard(
                        conn, memberguards.SHUSH, target_id, user_id, why,
                        expires_at=f"{on} 23:59:59",
                    )
                    answer = message_only(
                        shushed(target_id, on) if guard_id else already_shushed(target_id)
                    )
            elif verb == CHANNEL_BAN:
                where, remainder = in_a_channel(body)
                on, why = for_how_long(remainder)
                if where is None:
                    answer = message_only(CHANNEL_USAGE)
                elif on is None:
                    answer = message_only(DURATION_USAGE[CHANNEL_BAN])
                elif not why:
                    answer = message_only(TEXT_USAGE[CHANNEL_BAN])
                else:
                    guard_id = memberguards.open_guard(
                        conn, memberguards.CHANNEL_BAN, target_id, user_id, why,
                        channel_id=where, expires_at=f"{on} 23:59:59",
                    )
                    answer = message_only(
                        banned(target_id, where, on) if guard_id
                        else already_banned(target_id, where)
                    )
            elif verb == PURGE:
                request, problem = purge_requests.requested(
                    target_id, body, command.get("channel_id"))
                answer = (message_only(problem) if problem
                          else purge_requests.proposed(conn, request, user_id))
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
