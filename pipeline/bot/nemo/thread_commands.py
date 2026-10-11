import logging
import re

from bot.core import access, privileged, session
from bot.nemo import answer, case_actions, channel, chat
from bot.nemo.views import lines

log = logging.getLogger("bot.nemo")

WHO = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")

RESOLVE = "resolve"
RESOLVE_WORDS = ("!resolve", "?resolve")
CASE, CLAIM, ASSIGN, UNASSIGN, NOTE = "!case", "!claim", "!assign", "!unassign", "!note"
VERBS = (CASE, CLAIM, ASSIGN, UNASSIGN, NOTE)

SAVED = "white_check_mark"

NEEDS = {CASE: "case.read", CLAIM: "case.open", ASSIGN: "case.open", UNASSIGN: "case.open"}


def asked(text):
    words = (text or "").strip()
    if words.lower() in RESOLVE_WORDS:
        return RESOLVE, ""
    parts = words.split(None, 1)
    if not parts or parts[0].lower() not in VERBS:
        return None, None
    return parts[0].lower(), parts[1].strip() if len(parts) > 1 else ""


def done(say=(), react=None, keep=False):
    return {"say": list(say), "react": react, "keep": keep, "refused": None}


def refused(text):
    return {"say": [], "react": None, "keep": False, "refused": text}


def mentions(text):
    found = []
    for one in WHO.findall(text or ""):
        if one not in found:
            found.append(one)
    return found


def held_by(conn, case_id):
    return [row[0] for row in conn.execute(case_actions.HELD_BY, (case_id,)).fetchall()]


def case_link(conn, case_id, user_id, rest):
    return done(say=[lines.header(case_id, channel.case_url(case_id))])


def claim(conn, case_id, user_id, rest):
    if user_id in held_by(conn, case_id):
        return refused(lines.already_claimed(case_id))
    case_actions.claimed(conn, case_id, user_id)
    return done(say=[lines.claimed(user_id, case_id)])


def assign(conn, case_id, user_id, rest):
    named = mentions(rest)
    if not named:
        return refused(lines.ASSIGN_USAGE)
    held = held_by(conn, case_id)
    fresh = [one for one in named if one not in held]
    if not fresh:
        return refused(lines.already_assigned(case_id, named))
    case_actions.assign_people(conn, case_id, fresh, user_id)
    return done(say=lines.assigned(user_id, case_id, fresh))


def unassign(conn, case_id, user_id, rest):
    named = mentions(rest)
    if not named:
        return refused(lines.UNASSIGN_USAGE)
    held = held_by(conn, case_id)
    on = [one for one in named if one in held]
    if not on:
        return refused(lines.not_assigned(case_id, named))
    for one in on:
        case_actions.remove_assignee(conn, case_id, one, user_id)
    return done(say=[lines.unassigned(user_id, case_id, on)])


def note(conn, case_id, user_id, rest):
    about = WHO.match(rest)
    words = rest[about.end():].strip() if about else rest
    if not words:
        return refused(lines.NOTE_USAGE)
    if about:
        case_actions.member_note(conn, about.group(1), words, user_id)
    else:
        case_actions.keep_note(conn, case_id, words, user_id)
    return done(react=SAVED, keep=True)


RUN = {CASE: case_link, CLAIM: claim, ASSIGN: assign, UNASSIGN: unassign, NOTE: note}


def needed(verb, rest):
    if verb == NOTE:
        return "member.note" if WHO.match(rest) else "case.note"
    return NEEDS[verb]


def run(verb, rest, case_id, user_id):
    with session() as conn:
        allowed, refusal = access.may(conn, user_id, needed(verb, rest), case_id)
        if not allowed:
            return refused(lines.not_permitted(refusal))
        return RUN[verb](conn, case_id, user_id, rest)


def forget(client, channel_id, ts, failed):
    try:
        privileged.delete_message(channel_id, ts, max_retries=1)
        return True
    except Exception as failure:
        log.warning("nemo: could not take down the command at %s: %s", ts, failure)
    if failed:
        try:
            client.reactions_add(channel=channel_id, timestamp=ts, name=answer.STUCK)
        except Exception as failure:
            log.warning("nemo: could not mark the command at %s: %s", ts, failure)
    return False


def tell(client, channel_id, user_id, thread_ts, text):
    try:
        client.chat_postEphemeral(channel=channel_id, user=user_id, thread_ts=thread_ts, text=text)
    except Exception as failure:
        log.warning("nemo: could not tell %s %r: %s", user_id, text[:60], failure)


def reply(client, event, thread_ts, outcome):
    channel_id, ts = event["channel"], event["ts"]
    if outcome["refused"]:
        forget(client, channel_id, ts, failed=True)
        tell(client, channel_id, event.get("user"), thread_ts, outcome["refused"])
        return False

    for text in outcome["say"]:
        try:
            client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=text,
                                    unfurl_links=False, unfurl_media=False)
        except Exception as failure:
            log.warning("nemo: the thread did not hear %r: %s", text[:60], failure)
    if outcome["react"]:
        try:
            client.reactions_add(channel=channel_id, timestamp=ts, name=outcome["react"])
        except Exception as failure:
            log.warning("nemo: could not mark the command at %s: %s", ts, failure)
    if not outcome["keep"]:
        forget(client, channel_id, ts, failed=False)
    return True


def handle(client, event, thread_ts, verb, rest):
    with session() as conn:
        case_id = chat.case_of_thread(conn, thread_ts)
    if case_id is None:
        return None
    outcome = run(verb, rest, case_id, event.get("user"))
    reply(client, event, thread_ts, outcome)
    log.info("nemo: %s ran %s on case %s (%s)", event.get("user"), verb, case_id,
             "refused" if outcome["refused"] else "done")
    return case_id
