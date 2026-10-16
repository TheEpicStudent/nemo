import logging
import re

from bot.core import access, privileged, richtext, session
from bot.nemo import answer, case_actions, channel, chat
from bot.nemo.views import lines

log = logging.getLogger("bot.nemo")

USER_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")

RESOLVE = "resolve"
RESOLVE_COMMAND = re.compile(r"\A(?:~?\?|!)\s*resolve\Z", re.IGNORECASE)
CASE, CLAIM, ASSIGN, UNASSIGN, NOTE = "!case", "!claim", "!assign", "!unassign", "!note"
VERBS = (CASE, CLAIM, ASSIGN, UNASSIGN, NOTE)

SAVED_REACTION = "white_check_mark"

NEEDS = {CASE: "case.read", CLAIM: "case.open", ASSIGN: "case.open", UNASSIGN: "case.open"}


def parse_command(text):
    words = (text or "").strip()
    if RESOLVE_COMMAND.match(words):
        return RESOLVE, ""
    parts = words.split(None, 1)
    if not parts or parts[0].lower() not in VERBS:
        return None, None
    return parts[0].lower(), parts[1].strip() if len(parts) > 1 else ""


def accepted_outcome(say=(), react=None, retain=False):
    return {"say": list(say), "react": react, "retain": retain, "refused": None}


def refused_outcome(text):
    return {"say": [], "react": None, "retain": False, "refused": text}


def mentions(text):
    user_ids = []
    for one in USER_MENTION.findall(text or ""):
        if one not in user_ids:
            user_ids.append(one)
    return user_ids


def current_assignees(conn, case_id):
    return [row[0] for row in conn.execute(case_actions.CASE_ASSIGNEES, (case_id,)).fetchall()]


def case_link(conn, case_id, user_id, args):
    return accepted_outcome(say=[lines.header(case_id, channel.case_url(case_id))])


def claim(conn, case_id, user_id, args):
    if user_id in current_assignees(conn, case_id):
        return refused_outcome(lines.already_claimed(case_id))
    case_actions.record_claim(conn, case_id, user_id)
    return accepted_outcome(say=[lines.claimed(user_id, case_id)])


def assign(conn, case_id, user_id, args):
    mentioned_ids = mentions(args)
    if not mentioned_ids:
        return refused_outcome(lines.ASSIGN_USAGE)
    assigned = current_assignees(conn, case_id)
    new_ids = [one for one in mentioned_ids if one not in assigned]
    if not new_ids:
        return refused_outcome(lines.already_assigned(case_id, mentioned_ids))
    case_actions.assign_users(conn, case_id, new_ids, user_id)
    return accepted_outcome(say=lines.assigned(user_id, case_id, new_ids))


def unassign(conn, case_id, user_id, args):
    mentioned_ids = mentions(args)
    if not mentioned_ids:
        return refused_outcome(lines.UNASSIGN_USAGE)
    assigned = current_assignees(conn, case_id)
    to_remove = [one for one in mentioned_ids if one in assigned]
    if not to_remove:
        return refused_outcome(lines.not_assigned(case_id, mentioned_ids))
    for one in to_remove:
        case_actions.remove_assignee(conn, case_id, one, user_id)
    return accepted_outcome(say=[lines.unassigned(user_id, case_id, to_remove)])


def note_target(args):
    mention = USER_MENTION.match(args)
    if mention:
        return mention.group(1), args[mention.end():].strip()
    return richtext.leading_user_id(args)


def note(conn, case_id, user_id, args):
    member_id, words = note_target(args)
    if not words:
        return refused_outcome(lines.NOTE_USAGE)
    if member_id:
        case_actions.member_note(conn, member_id, words, user_id)
    else:
        case_actions.add_note(conn, case_id, words, user_id)
    return accepted_outcome(react=SAVED_REACTION, retain=True)


HANDLERS = {CASE: case_link, CLAIM: claim, ASSIGN: assign, UNASSIGN: unassign, NOTE: note}


def needed(verb, args):
    if verb == NOTE:
        return "member.note" if note_target(args)[0] else "case.note"
    return NEEDS[verb]


def run(verb, args, case_id, user_id):
    with session() as conn:
        allowed, refusal = access.may(conn, user_id, needed(verb, args), case_id)
        if not allowed:
            return refused_outcome(refusal)
        return HANDLERS[verb](conn, case_id, user_id, args)


def delete_command(client, channel_id, ts, failed):
    try:
        privileged.delete_message(channel_id, ts, max_retries=1)
        return True
    except Exception as failure:
        log.warning("nemo: could not take down the command at %s: %s", ts, failure)
    if failed:
        try:
            client.reactions_add(channel=channel_id, timestamp=ts, name=answer.FAILED_REACTION)
        except Exception as failure:
            log.warning("nemo: could not mark the command at %s: %s", ts, failure)
    return False


def send_ephemeral(client, channel_id, user_id, thread_ts, text):
    try:
        client.chat_postEphemeral(channel=channel_id, user=user_id, thread_ts=thread_ts, text=text)
    except Exception as failure:
        log.warning("nemo: could not tell %s %r: %s", user_id, text[:60], failure)


def reply(client, event, thread_ts, outcome):
    channel_id, ts = event["channel"], event["ts"]
    if outcome["refused"]:
        delete_command(client, channel_id, ts, failed=True)
        send_ephemeral(client, channel_id, event.get("user"), thread_ts, outcome["refused"])
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
    if not outcome["retain"]:
        delete_command(client, channel_id, ts, failed=False)
    return True


def handle(client, event, thread_ts, verb, args):
    with session() as conn:
        case_id = chat.case_of_thread(conn, thread_ts)
    if case_id is None:
        return None
    outcome = run(verb, args, case_id, event.get("user"))
    reply(client, event, thread_ts, outcome)
    log.info("nemo: %s ran %s on case %s (%s)", event.get("user"), verb, case_id,
             "refused" if outcome["refused"] else "done")
    return case_id
