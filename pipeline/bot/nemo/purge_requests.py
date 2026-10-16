import re
from collections import namedtuple

from psycopg import errors

from bot.core import access, audit, session
from bot.nemo import channel
from bot.nemo.enforcement import purge

CONFIRM = "purge_confirm"
CANCEL = "purge_cancel"
MAX_REASON_LENGTH = 500
CONFIRMATION_MINUTES = 10

CHANNEL_MENTION = re.compile(r"<#([CG][A-Z0-9]+)(?:\|[^>]*)?>")
NUMBER = re.compile(r"\A\d{1,6}\Z")

USAGE = (
    "Usage: */nemo purge 50* · */nemo purge #channel 50* · "
    "*/nemo purge @member* · */nemo purge @member #channel*"
)
NAME_A_CHANNEL = "Name the channel: */nemo purge #channel 50*"
NEED_A_NUMBER = "Usage: */nemo purge #channel 50* · */nemo purge @member #channel*"
OUT_OF_RANGE = f"Count must be 1 to {purge.CAP:,}"
TOO_LONG = f"Reason must be under {MAX_REASON_LENGTH} characters"
NOT_FOUND = "Purge already confirmed or cancelled"
EXPIRED = "Confirmation expired"
ALREADY_RUNNING = "Purge already running"

Request = namedtuple("Request", "channel_id member_id wanted reason")

MESSAGE_COUNT = """
SELECT count(*)
FROM archive.message
WHERE deleted_at IS NULL
  AND (%(member_id)s::text IS NULL OR author_id = %(member_id)s)
  AND (%(channel_id)s::text IS NULL OR channel_id = %(channel_id)s)
  AND coalesce(subtype, '') NOT IN ('channel_join', 'channel_leave')
"""

DELETE_STALE_PROPOSALS = "DELETE FROM fd.purges WHERE state = 'proposed' AND asked_at < now() - interval '1 day'"

INSERT_PROPOSAL = """
INSERT INTO fd.purges (channel_id, member_id, wanted, reason, asked_by, state, source, found)
VALUES (%s, %s, %s, %s, %s, 'proposed', 'slack', %s)
RETURNING id
"""

PROPOSAL = f"""
SELECT channel_id, member_id, wanted, reason, asked_by,
       asked_at > now() - interval '{CONFIRMATION_MINUTES} minutes'
FROM fd.purges
WHERE id = %s AND state = 'proposed'
FOR UPDATE
"""

MARK_QUEUED = "UPDATE fd.purges SET state = 'asked', asked_at = now() WHERE id = %s AND state = 'proposed'"

DELETE_PROPOSAL = "DELETE FROM fd.purges WHERE id = %s AND state = 'proposed'"


def capability_for(member_id):
    return "member.purge" if member_id else "channel.purge"


def parse_request(member_id, body, here):
    text = body or ""
    where = CHANNEL_MENTION.search(text)
    channel_id = where.group(1) if where else None
    if where:
        text = f"{text[:where.start()]} {text[where.end():]}"

    words = text.split()
    count = next((word for word in words if NUMBER.match(word)), None)
    if count is not None:
        words.remove(count)
    reason = " ".join(words) or None

    if member_id is None and count is None:
        return None, NEED_A_NUMBER if channel_id else USAGE
    if member_id is None and channel_id is None:
        if not (here or "").startswith(("C", "G")):
            return None, NAME_A_CHANNEL
        channel_id = here
    if count is not None and not 1 <= int(count) <= purge.CAP:
        return None, OUT_OF_RANGE
    if reason and len(reason) > MAX_REASON_LENGTH:
        return None, TOO_LONG
    return Request(channel_id, member_id, int(count) if count else None, reason), None


def estimate_count(conn, request):
    if request.wanted:
        return None
    return conn.execute(MESSAGE_COUNT, {"member_id": request.member_id,
                                        "channel_id": request.channel_id}).fetchone()[0]


def plural(count):
    return "message" if count == 1 else "messages"


def describe(request, estimate=None):
    if request.wanted:
        amount = f"the last {request.wanted:,} {plural(request.wanted)}"
    elif estimate and estimate > purge.CAP:
        amount = f"the last {purge.CAP:,} of {estimate:,} messages"
    elif estimate:
        amount = f"all {estimate:,} {plural(estimate)}"
    else:
        amount = "every message"
    from_member = f" from <@{request.member_id}>" if request.member_id else ""
    where = f" in <#{request.channel_id}>" if request.channel_id else " in every channel"
    replies = "" if request.member_id else ", with their thread replies"
    return f"{amount}{from_member}{where}{replies}"


def prompt(purge_id, request, estimate):
    text = f"Confirm purging {describe(request, estimate)}"
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    if request.reason:
        blocks.append({"type": "context",
                       "elements": [{"type": "mrkdwn", "text": f"Reason: {request.reason}"}]})
    blocks.append({
        "type": "actions",
        "elements": [
            {"type": "button", "action_id": CONFIRM, "style": "danger", "value": str(purge_id),
             "text": {"type": "plain_text", "text": "Purge"}},
            {"type": "button", "action_id": CANCEL, "value": str(purge_id),
             "text": {"type": "plain_text", "text": "Cancel"}},
        ],
    })
    return {"text": text, "blocks": blocks}


def propose(conn, request, user_id):
    estimate = estimate_count(conn, request)
    conn.execute(DELETE_STALE_PROPOSALS)
    purge_id = conn.execute(INSERT_PROPOSAL, (request.channel_id, request.member_id, request.wanted,
                                              request.reason, user_id, estimate)).fetchone()[0]
    return prompt(purge_id, request, estimate)


def log_channel_mention():
    log_channel_id = channel.log_channel()
    return f"<#{log_channel_id}>" if log_channel_id else "log channel"


def confirmation_text(request):
    return f"Purging {describe(request)} · Result in {log_channel_mention()}"


def confirm(purge_id, user_id):
    with session() as conn:
        row = conn.execute(PROPOSAL, (purge_id,)).fetchone()
        if row is None:
            return NOT_FOUND
        channel_id, member_id, wanted, reason, asked_by, within_window = row
        if asked_by != user_id:
            return f"Only <@{asked_by}> can confirm"
        if not within_window:
            conn.execute(DELETE_PROPOSAL, (purge_id,))
            return EXPIRED

        allowed, refusal = access.may(conn, user_id, "member.purge" if member_id else "channel.purge")
        if not allowed:
            conn.execute(DELETE_PROPOSAL, (purge_id,))
            return refusal

        try:
            with conn.transaction():
                conn.execute(MARK_QUEUED, (purge_id,))
        except errors.UniqueViolation:
            conn.execute(DELETE_PROPOSAL, (purge_id,))
            return ALREADY_RUNNING

        audit.record(conn, "member_purge" if member_id else "channel_purge", purge_id, "queued",
                     user_id, subject_user_id=member_id,
                     after={"channel_id": channel_id, "member_id": member_id, "wanted": wanted,
                            "reason": reason, "source": "slack"})
    return confirmation_text(Request(channel_id, member_id, wanted, reason))


def cancel(purge_id, user_id):
    with session() as conn:
        row = conn.execute(PROPOSAL, (purge_id,)).fetchone()
        if row is not None and row[4] == user_id:
            conn.execute(DELETE_PROPOSAL, (purge_id,))
            return True
    return False
