import logging
import os
import time

from psycopg.types.json import Jsonb

from bot.core import parse
from bot.core.formatting import quote_text
from bot.nemo import answer, views, attachments, channels, chat, profile

log = logging.getLogger("bot.nemo")


CASE = """
SELECT c.id, c.category_key, c.resolved_at,
       r.id, r.is_anonymous, r.reporter_user_id, r.body, r.forwarded_ts, r.received_at,
       v.id, r.card_digest, c.resolution, r.card_channel_id, r.header_ts
FROM fd.cases c
JOIN fd.case_reports r ON r.case_id = c.id
LEFT JOIN fd.intake_conversations v ON v.report_id = r.id
WHERE c.id = %s
ORDER BY r.id
LIMIT 1
"""


SUBJECTS = """
SELECT user_id FROM fd.case_participants
WHERE case_id = %s AND role = 'subject'
ORDER BY user_id
"""


ASSIGNEES = """
SELECT user_id FROM fd.case_assignees WHERE case_id = %s ORDER BY assigned_at
"""


FIRST_MESSAGE = """
SELECT m.id, m.body, m.mirrored_ts, m.blocks, coalesce(o.body, m.body)
FROM fd.intake_messages m
LEFT JOIN fd.intake_revisions o ON o.message_id = m.id AND o.seq = 0
WHERE m.conversation_id = %s AND m.direction = 'inbound'
ORDER BY m.posted_at, m.id
LIMIT 1
"""


SHOWN = """
SELECT m.id, coalesce(o.body, m.body), m.posted_at, m.mirrored_ts, m.deleted_at,
       c.handed_off_at
FROM fd.intake_messages m
JOIN fd.intake_conversations c ON c.id = m.conversation_id
LEFT JOIN fd.intake_revisions o ON o.message_id = m.id AND o.seq = 0
WHERE m.conversation_id = %s AND m.direction = 'inbound'
ORDER BY m.posted_at, m.id
"""


CONVERSATION_SHARES = """
SELECT s.message_id, s.kind, s.source_channel_id, s.source_ts, s.permalink
FROM fd.intake_shares s
JOIN fd.intake_messages m ON m.id = s.message_id
WHERE m.conversation_id = %s
ORDER BY s.id
"""


UNFURL_OF = """
SELECT conversation_id, unfurl_ts, unfurl_digest, unfurled_at
FROM fd.intake_messages WHERE id = %s
FOR UPDATE
"""


UNFURLED = """
UPDATE fd.intake_messages
SET unfurl_ts = coalesce(%s, unfurl_ts), unfurl_digest = %s,
    unfurled_at = coalesce(unfurled_at, now())
WHERE id = %s
"""


FORWARDED_FILES = """
SELECT mf.file_id, f.slack_file_id, f.name, f.mimetype, f.stored_key, mf.mirrored_file_id
FROM fd.intake_message_files mf
JOIN fd.intake_files f ON f.id = mf.file_id
WHERE mf.message_id = %s AND mf.forwarded AND f.fetch_state = 'stored'
ORDER BY mf.seq
"""


UNFURLS_ON_CASE = """
SELECT m.id, r.forwarded_ts, r.card_channel_id
FROM fd.intake_messages m
JOIN fd.intake_conversations c ON c.id = m.conversation_id
JOIN fd.case_reports r ON r.id = c.report_id
WHERE r.case_id = %s AND r.forwarded_ts IS NOT NULL AND m.direction = 'inbound'
  AND m.mirrored_ts IS NOT NULL AND m.deleted_at IS NULL
  AND (m.unfurled_at IS NULL OR m.unfurl_ts IS NOT NULL)
ORDER BY m.posted_at, m.id
"""


LIVE_ACTION_COUNT = """
SELECT count(*) FROM fd.actions WHERE case_id = %s AND reversed_at IS NULL
"""


SHARES = """
SELECT s.kind, s.source_channel_id, s.source_channel_name, s.source_ts, s.permalink,
       s.is_reachable, s.source_author_user_id, s.source_body, s.raw
FROM fd.intake_shares s
WHERE s.message_id = %s
ORDER BY s.id
"""


CLAIM_CARD = """
SELECT forwarded_ts FROM fd.case_reports WHERE id = %s FOR UPDATE
"""


FOLLOW_UP = """
SELECT m.body, m.mirrored_ts, r.forwarded_ts, m.conversation_id,
       r.is_anonymous, r.reporter_user_id, r.card_channel_id
FROM fd.intake_messages m
JOIN fd.intake_conversations c ON c.id = m.conversation_id
LEFT JOIN fd.case_reports r ON r.id = c.report_id
WHERE m.id = %s
"""


ANONYMOUS = "Anonymous"


def digest_of(blocks, mark=None):
    return parse.digest(mark, blocks, None)


OPEN_MARK = "hourglass_flowing_sand"
MERGED_MARK = "repeat"
DONE_MARK = "white_check_mark"
CARD_MARKS = (OPEN_MARK, MERGED_MARK, DONE_MARK, "check")
NOT_CONDUCT_MARKS = ("x", "heavy_multiplication_x", "negative_squared_cross_mark")
QUIET = ("already_reacted", "no_reaction")


STATE = "mark:"


def card_state(mark):
    return f"{STATE}{mark or ''}"


def drawn_before_states(stored):
    return not str(stored or "").startswith(STATE)


def card_mark(case):
    if not case.get("resolved_at"):
        return OPEN_MARK
    return MERGED_MARK if case.get("resolution") == "duplicate" else DONE_MARK


def crossed_by_hand(client, channel_id, ts):
    try:
        found = client.reactions_get(channel=channel_id, timestamp=ts)
    except Exception as failure:
        log.warning("nemo: could not read the reactions on %s: %s", ts, failure)
        return False
    reactions = ((found or {}).get("message") or {}).get("reactions") or []
    return any((one.get("name") or "").split("::")[0] in NOT_CONDUCT_MARKS for one in reactions)


def react(client, method, channel_id, ts, name):
    try:
        getattr(client, method)(channel=channel_id, timestamp=ts, name=name)
    except Exception as failure:
        if not any(one in str(failure) for one in QUIET):
            log.warning("nemo: could not change %s on %s: %s", name, ts, failure)


def mark_card(client, channel_id, ts, case, fresh=False):
    wanted = card_mark(case)
    if case.get("resolution") == "not_conduct" and crossed_by_hand(client, channel_id, ts):
        wanted = None
    if not fresh:
        for name in CARD_MARKS:
            if name != wanted:
                react(client, "reactions_remove", channel_id, ts, name)
    if wanted:
        react(client, "reactions_add", channel_id, ts, wanted)


def root_mark(case):
    return card_mark(case) if case.get("resolved_at") else None


def mark_root(client, channel_id, root_ts, card_ts, case, fresh=False):
    wanted = root_mark(case)
    if case.get("resolution") == "not_conduct" and crossed_by_hand(client, channel_id, root_ts):
        wanted = None
    if not fresh:
        for name in CARD_MARKS:
            if name != wanted:
                react(client, "reactions_remove", channel_id, root_ts, name)
            react(client, "reactions_remove", channel_id, card_ts, name)
    if wanted:
        react(client, "reactions_add", channel_id, root_ts, wanted)


_internal_log = {}


def internal_log_channel(conn=None):
    if conn is not None:
        _internal_log["id"] = channels.setting(conn, channels.INTERNAL_LOG) or None
    return _internal_log.get("id") or os.environ["INTERNAL_LOG_CHANNEL_ID"]


_react = {}


def react_channels(conn=None):
    if conn is not None:
        _react["ids"] = channels.react_channels(conn)
    return _react.get("ids") or set()


def case_channels(conn=None):
    return {internal_log_channel(conn)} | react_channels(conn)


def card_channel(case, channel_id=None, conn=None):
    return room_of(case.get("card_channel_id"), channel_id, conn)


def room_of(stored, channel_id=None, conn=None):
    return stored or channel_id or internal_log_channel(conn)


CARD_ROOM = """
SELECT coalesce(
    (SELECT r.card_channel_id FROM fd.case_reports r
      WHERE r.case_id = %(case_id)s AND r.forwarded_ts IS NOT NULL
      ORDER BY r.id LIMIT 1),
    (SELECT k.card_channel_id FROM fd.cases k WHERE k.id = %(case_id)s)
)
"""


def card_room(conn, case_id, channel_id=None):
    row = conn.execute(CARD_ROOM, {"case_id": case_id}).fetchone()
    return (row and row[0]) or channel_id or internal_log_channel(conn)


THREAD_FOR_CASE = """
SELECT coalesce(
    (SELECT r.forwarded_ts FROM fd.case_reports r
      WHERE r.case_id = %(case_id)s AND r.forwarded_ts IS NOT NULL
      ORDER BY r.id LIMIT 1),
    (SELECT coalesce(k.card_thread_ts, k.card_ts) FROM fd.cases k WHERE k.id = %(case_id)s)
)
"""


def thread_for(conn, case_id):
    row = conn.execute(THREAD_FOR_CASE, {"case_id": case_id}).fetchone()
    return row[0] if row else None


def post_line(client, conn, case_id, text):
    thread = thread_for(conn, case_id)
    if not thread:
        return None
    try:
        return client.chat_postMessage(
            channel=card_room(conn, case_id),
            thread_ts=thread,
            text=text,
            unfurl_links=False,
            unfurl_media=False,
        )["ts"]
    except Exception as failure:
        log.warning("nemo: case %s did not hear %r: %s", case_id, text[:60], failure)
        return None


def post_merge_note(client, conn, keep, closed, by):
    if not closed:
        return None
    text = views.lines.merged(by, closed, keep, case_url)
    for case_id in (keep, *closed):
        post_line(client, conn, case_id, text)
    return text


HEADER_POSTED = """
UPDATE fd.case_reports SET header_ts = %s WHERE id = %s AND header_ts IS NULL
"""


def post_header(client, conn, case, room, thread_ts):
    if case.get("header_ts") or not views.report.needs_header(case):
        return None
    try:
        sent = client.chat_postMessage(
            channel=room,
            thread_ts=thread_ts,
            text=f"Case {case['case_id']}",
            blocks=views.report.header_blocks(case),
            unfurl_links=False,
            unfurl_media=False,
        )
    except Exception as failure:
        log.warning("nemo: case %s has no header in its thread: %s", case["case_id"], failure)
        return None
    conn.execute(HEADER_POSTED, (sent["ts"], case["report_id"]))
    return sent["ts"]


def read_linked(client, channel_id, ts, thread_ts=None):
    try:
        if thread_ts and thread_ts != ts:
            found = client.conversations_replies(
                channel=channel_id, ts=thread_ts, oldest=ts, latest=ts, inclusive=True, limit=5
            )
        else:
            found = client.conversations_history(
                channel=channel_id, oldest=ts, latest=ts, inclusive=True, limit=1
            )
    except Exception as failure:
        log.info("nemo: could not read %s in %s: %s", ts, channel_id, failure)
        return None
    message = next((one for one in found.get("messages") or [] if one.get("ts") == ts), None)
    if message is None:
        return None
    return {
        "kind": "link",
        "source_channel_id": channel_id,
        "source_ts": ts,
        "source_author_user_id": message.get("user"),
        "source_body": message.get("text"),
        "permalink": None,
        "is_reachable": bool((message.get("text") or "").strip()),
        "raw": None,
    }


def linked_shares(client, text):
    shares, seen = [], set()
    for one in views.linked.occurrences(text):
        key = (one["channel_id"], one["ts"])
        if key in seen:
            continue
        seen.add(key)
        found = read_linked(client, one["channel_id"], one["ts"], one["thread_ts"])
        if found:
            shares.append(found)
    return shares


OPENING_TO_UNFURL = """
SELECT id, body FROM fd.case_chat
WHERE case_id = %s AND mirrored_as = 'card' AND deleted_at IS NULL AND unfurl_ts IS NULL
ORDER BY id LIMIT 1
"""

OPENING_UNFURLED = "UPDATE fd.case_chat SET unfurl_ts = %s WHERE id = %s AND unfurl_ts IS NULL"


def unfurl_opening(client, conn, case_id, channel_id, thread_ts):
    row = conn.execute(OPENING_TO_UNFURL, (case_id,)).fetchone()
    if row is None:
        return None
    chat_id, body = row
    numbered = views.linked.numbering(body, [], 1)
    if not numbered["links"]:
        return None
    found = views.linked.items(numbered, linked_shares(client, body))
    try:
        sent = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=views.linked.fallback(found),
            blocks=views.linked.reply_blocks(found),
            unfurl_links=False,
            unfurl_media=False,
        )
    except Exception as failure:
        log.warning("nemo: case %s's links would not unfurl: %s", case_id, failure)
        return None
    conn.execute(OPENING_UNFURLED, (sent["ts"], chat_id))
    return sent["ts"]


def app_url(path):
    host = os.environ.get("APP_HOST")
    if not host:
        return None
    scheme = "http" if host.startswith("localhost") or host.startswith("127.") else "https"
    return f"{scheme}://{host}{path}"


def case_url(case_id):
    return app_url(f"/fd/cases/{case_id}")


def member_url(user_id):
    return app_url(f"/fd/members/{user_id}")


def channel_url(channel_id):
    return app_url(f"/fd/channels/{channel_id}")


def gather(conn, case_id):
    row = conn.execute(CASE, (case_id,)).fetchone()
    if not row:
        return None
    case = {
        "case_id": row[0],
        "category_key": row[1],
        "resolved_at": row[2],
        "report_id": row[3],
        "is_anonymous": row[4],
        "reporter_user_id": row[5],
        "body": row[6],
        "forwarded_ts": row[7],
        "received_at": row[8],
        "conversation_id": row[9],
        "card_digest": row[10],
        "resolution": row[11],
        "card_channel_id": row[12],
        "header_ts": row[13],
        "url": case_url(row[0]),
        "shares": [],
        "message_id": None,
        "blocks": None,
    }

    case["subjects"] = [
        subject[0] for subject in conn.execute(SUBJECTS, (case["case_id"],)).fetchall()
    ]
    case["assignees"] = [
        held[0] for held in conn.execute(ASSIGNEES, (case["case_id"],)).fetchall()
    ]
    case["live_actions"] = conn.execute(LIVE_ACTION_COUNT, (case["case_id"],)).fetchone()[0]

    convo = case["conversation_id"]
    if convo is None:
        return case

    first = conn.execute(FIRST_MESSAGE, (convo,)).fetchone()
    if first:
        case["message_id"] = first[0]
        case["mirrored_ts"] = first[2]
        case["blocks"] = first[3]
        if not case["body"]:
            case["body"] = first[1]

    case["shares"] = shares_for(conn, case["message_id"])
    if first:
        case["numbering"] = views.linked.numbering(first[4], case["shares"], 1)
    return case


def shares_for(conn, message_id):
    return [
        {
            "kind": one[0],
            "source_channel_id": one[1],
            "source_channel_name": one[2],
            "source_ts": one[3],
            "permalink": one[4],
            "is_reachable": one[5],
            "source_author_user_id": one[6],
            "source_body": one[7],
            "raw": one[8],
        }
        for one in conn.execute(SHARES, (message_id,)).fetchall()
    ]


def numbers(conn, conversation_id):
    shares = {}
    for message_id, kind, channel_id, ts, permalink in conn.execute(
        CONVERSATION_SHARES, (conversation_id,)
    ).fetchall():
        shares.setdefault(message_id, []).append({
            "kind": kind, "source_channel_id": channel_id, "source_ts": ts, "permalink": permalink,
        })

    found = {}
    start = 1
    rows = conn.execute(SHOWN, (conversation_id,)).fetchall()
    for at, (message_id, text, posted_at, mirrored, deleted, handed_off) in enumerate(rows):
        if at and not (handed_off and posted_at > handed_off):
            continue
        if at and deleted and not mirrored:
            continue
        found[message_id] = views.linked.numbering(text, shares.get(message_id), start)
        start += views.linked.size(found[message_id])
    return found


def forwarded_files(client, conn, message_id):
    held = {}
    uploaded = False
    for file_id, slack_file_id, name, mimetype, sha, mirrored in conn.execute(
        FORWARDED_FILES, (message_id,)
    ).fetchall():
        shown = name or (sha or slack_file_id)[:12]
        if not attachments.shows_inline(mimetype):
            held[slack_file_id] = {"id": None, "name": shown, "image": False}
            continue
        if not mirrored:
            body, _ = attachments.blobs.body_of(conn, sha)
            if body is None:
                continue
            mirrored = attachments.held_in_slack(client, shown, body)
            if not mirrored:
                continue
            conn.execute(attachments.MIRRORED, (mirrored, message_id, file_id))
            uploaded = True
        held[slack_file_id] = {"id": mirrored, "name": shown, "image": True}
    if uploaded:
        time.sleep(attachments.FILE_INDEX_DELAY)
    return held


def unfurl(client, conn, message_id, channel_id, thread_ts):
    row = conn.execute(UNFURL_OF, (message_id,)).fetchone()
    if row is None:
        return None
    conversation_id, posted, digest, handled = row
    if handled and not posted:
        return None

    found = views.linked.items(
        numbers(conn, conversation_id).get(message_id), shares_for(conn, message_id)
    )
    blocks = views.linked.reply_blocks(found, forwarded_files(client, conn, message_id))

    if not blocks:
        if not posted:
            conn.execute(UNFURLED, (None, None, message_id))
        return posted

    fingerprint = digest_of(blocks)
    if posted:
        if fingerprint != digest:
            client.chat_update(
                channel=channel_id, ts=posted, text=views.linked.fallback(found), blocks=blocks
            )
            conn.execute(UNFURLED, (None, fingerprint, message_id))
        return posted

    sent = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=views.linked.fallback(found),
        blocks=blocks,
        unfurl_links=False,
        unfurl_media=False,
    )
    conn.execute(UNFURLED, (sent["ts"], fingerprint, message_id))
    log.info("nemo: message %s has its links unfurled at %s", message_id, sent["ts"])
    return sent["ts"]


def carry_unfurls(client, conn, case_id, channel_id=None):
    carried = 0
    for message_id, thread_ts, stored in conn.execute(UNFURLS_ON_CASE, (case_id,)).fetchall():
        try:
            if unfurl(client, conn, message_id, room_of(stored, channel_id, conn), thread_ts):
                carried += 1
        except Exception as failure:
            log.warning("nemo: message %s's links would not unfurl: %s", message_id, failure)
    return carried


def post_report(client, conn, case_id, channel_id=None, thread_ts=None):
    case = gather(conn, case_id)
    if case is None:
        log.warning("nemo: case %s has no report to post", case_id)
        return None
    if case["forwarded_ts"]:
        log.info("nemo: case %s is already in the internal_log", case_id)
        return case["forwarded_ts"]

    held = conn.execute(CLAIM_CARD, (case["report_id"],)).fetchone()
    if held and held[0]:
        log.info("nemo: case %s went up while we were asking, leaving it", case_id)
        return held[0]

    built = views.report.build_blocks(case)
    room = channel_id or internal_log_channel(conn)
    sent = client.chat_postMessage(
        channel=room,
        thread_ts=thread_ts,
        text=views.report.fallback(case),
        blocks=built,
        metadata=views.report.metadata(case),
        unfurl_links=False,
        unfurl_media=False,
        **only_the_face(client, case["is_anonymous"], case["reporter_user_id"]),
    )
    ts = sent["ts"]

    conn.execute(
        "UPDATE fd.case_reports SET forwarded_ts = %s, card_digest = %s, card_channel_id = %s, "
        "card_rendered_at = now() WHERE id = %s AND forwarded_ts IS NULL",
        (ts, card_state(card_mark(case)), room, case["report_id"]),
    )
    mark_card(client, room, ts, case, fresh=True)
    post_header(client, conn, case, room, ts)
    if case["message_id"]:
        conn.execute(
            "UPDATE fd.intake_messages SET mirrored_ts = %s, mirrored_at = now() "
            "WHERE id = %s",
            (ts, case["message_id"]),
        )
        try:
            unfurl(client, conn, case["message_id"], room, ts)
        except Exception as failure:
            log.warning("nemo: case %s's links would not unfurl: %s", case_id, failure)
    if case["message_id"]:
        attachments.share(
            client, conn, case["message_id"], room, ts,
            wearing=as_reporter(client, case["is_anonymous"], case["reporter_user_id"]),
        )

    log.info("nemo: case %s posted to the internal_log at %s", case_id, ts)
    return ts


def anonymous_face():
    found = os.environ.get("ANONYMOUS_ICON_URL")
    if found:
        return found

    host = os.environ.get("APP_HOST", "")
    if not host or host.startswith(("localhost", "127.")):
        return None
    return app_url("/anonymous.png")


def only_the_face(client, anonymous, reporter_user_id):
    worn = as_reporter(client, anonymous, reporter_user_id)
    worn.pop("metadata", None)
    return worn


def as_reporter(client, anonymous, reporter_user_id):
    if anonymous or not reporter_user_id:
        worn = {"username": ANONYMOUS}
        icon = anonymous_face()
        if icon:
            worn["icon_url"] = icon
        return worn

    seen = profile.profile(client, reporter_user_id)
    wearing = {"username": seen["name"]}
    if seen["icon"]:
        wearing["icon_url"] = seen["icon"]
    wearing["metadata"] = {
        "event_type": "nemo_message",
        "event_payload": {"source_user_id": reporter_user_id},
    }
    return wearing


def post_follow_up(client, conn, message_id, channel_id=None):
    row = conn.execute(FOLLOW_UP, (message_id,)).fetchone()
    if not row:
        return None
    body, mirrored, forwarded, conversation_id, anonymous, reporter, stored = row
    if mirrored:
        return mirrored
    if not forwarded:
        log.warning("nemo: message %s has no card to hang under", message_id)
        return None

    room = room_of(stored, channel_id, conn)
    numbered = numbers(conn, conversation_id).get(message_id)
    ts = attachments.share(
        client, conn, message_id, room, forwarded,
        wearing=as_reporter(client, anonymous, reporter),
        body=views.linked.numbered_text(
            views.report.escape_but_mentions(quote_text(body)), numbered
        ),
        unfurl=not (numbered and numbered["links"]),
    )
    if ts is None:
        log.info("nemo: message %s had nothing to carry", message_id)
        return None

    conn.execute(
        "UPDATE fd.intake_messages SET mirrored_ts = %s, mirrored_at = now() "
        "WHERE id = %s AND mirrored_ts IS NULL",
        (ts, message_id),
    )
    try:
        unfurl(client, conn, message_id, room, forwarded)
    except Exception as failure:
        log.warning("nemo: message %s's links would not unfurl: %s", message_id, failure)
    log.info("nemo: message %s carried into the internal_log at %s", message_id, ts)
    return ts


def refresh_card(client, conn, case_id, channel_id=None):
    case = gather(conn, case_id)
    if case is None:
        return None
    if not case["forwarded_ts"]:
        return post_report(client, conn, case_id, channel_id)

    state = card_state(card_mark(case))
    if state == case["card_digest"]:
        return case["forwarded_ts"]

    room = card_channel(case, channel_id, conn)
    if drawn_before_states(case["card_digest"]):
        try:
            client.chat_update(
                channel=room,
                ts=case["forwarded_ts"],
                text=views.report.fallback(case),
                blocks=views.report.build_blocks(case),
            )
        except Exception as failure:
            if not is_foreign_message_error(failure):
                raise
            log.warning("nemo: case %s keeps its card as it was, slack would not edit it: %s",
                        case_id, failure)
            conn.execute(REDRAWN, (state, case["report_id"]))
            return case["forwarded_ts"]

    conn.execute(REDRAWN, (state, case["report_id"]))
    mark_card(client, room, case["forwarded_ts"], case)
    post_header(client, conn, case, room, case["forwarded_ts"])
    log.info("nemo: case %s is now %s", case_id, state)
    return case["forwarded_ts"]


NOT_OURS = ("cant_update_message", "message_not_found", "edit_window_closed")

REDRAWN = """
UPDATE fd.case_reports SET card_digest = %s, card_rendered_at = now() WHERE id = %s
"""


def is_foreign_message_error(failure):
    text = str(failure)
    return any(one in text for one in NOT_OURS)


def post_ephemeral(client, body, text):
    client.chat_postEphemeral(
        channel=body["channel"]["id"],
        user=body["user"]["id"],
        thread_ts=body["message"].get("thread_ts") or body["message"]["ts"],
        text=text,
    )


WOKE = """
SELECT woke_from FROM fd.cases
WHERE id = %s AND woke_at IS NOT NULL AND woke_notified_at IS NULL
"""


REOPEN_ANNOUNCED = """
UPDATE fd.cases SET woke_notified_at = now() WHERE id = %s AND woke_notified_at IS NULL
"""


UNANNOUNCED_REOPENS = """
SELECT id FROM fd.cases
WHERE woke_at IS NOT NULL AND woke_notified_at IS NULL
ORDER BY woke_at LIMIT 50
"""


SOMETHING_TO_CARRY = """
coalesce(btrim(m.body), '') <> '' OR EXISTS (
    SELECT 1 FROM fd.intake_message_files mf
    JOIN fd.intake_files f ON f.id = mf.file_id
    WHERE mf.message_id = m.id AND mf.mirrored_at IS NULL AND NOT mf.forwarded
      AND f.fetch_state IN ('pending', 'stored')
) OR EXISTS (
    SELECT 1 FROM fd.intake_shares s WHERE s.message_id = m.id AND s.kind = 'forward'
)
"""

FOLLOW_UPS_WAITING = f"""
SELECT m.id
FROM fd.intake_messages m
JOIN fd.intake_conversations c ON c.id = m.conversation_id
JOIN fd.case_reports r ON r.id = c.report_id
WHERE r.case_id = %s AND m.direction = 'inbound' AND m.mirrored_ts IS NULL
  AND m.deleted_at IS NULL AND c.handed_off_at IS NOT NULL
  AND m.posted_at > c.handed_off_at AND ({SOMETHING_TO_CARRY})
ORDER BY m.posted_at, m.id
"""


FOLLOW_UPS_ANYWHERE = f"""
SELECT DISTINCT r.case_id
FROM fd.intake_messages m
JOIN fd.intake_conversations c ON c.id = m.conversation_id
JOIN fd.case_reports r ON r.id = c.report_id
WHERE m.direction = 'inbound' AND m.mirrored_ts IS NULL AND m.deleted_at IS NULL
  AND c.handed_off_at IS NOT NULL AND m.posted_at > c.handed_off_at
  AND ({SOMETHING_TO_CARRY})
LIMIT 100
"""


FILES_WAITING = """
SELECT DISTINCT r.case_id
FROM fd.intake_message_files mf
JOIN fd.intake_files f ON f.id = mf.file_id
JOIN fd.intake_messages m ON m.id = mf.message_id
JOIN fd.intake_conversations c ON c.id = m.conversation_id
JOIN fd.case_reports r ON r.id = c.report_id
WHERE mf.mirrored_at IS NULL AND f.fetch_state = 'stored' AND NOT mf.forwarded
  AND m.direction = 'inbound' AND r.forwarded_ts IS NOT NULL
LIMIT 50
"""

FILES_ON_CASE = """
SELECT DISTINCT mf.message_id, r.forwarded_ts, r.is_anonymous, r.reporter_user_id,
       r.card_channel_id
FROM fd.intake_message_files mf
JOIN fd.intake_files f ON f.id = mf.file_id
JOIN fd.intake_messages m ON m.id = mf.message_id
JOIN fd.intake_conversations c ON c.id = m.conversation_id
JOIN fd.case_reports r ON r.id = c.report_id
WHERE r.case_id = %s AND mf.mirrored_at IS NULL AND f.fetch_state = 'stored'
  AND NOT mf.forwarded AND m.direction = 'inbound' AND r.forwarded_ts IS NOT NULL
ORDER BY mf.message_id
"""


def waiting_files(conn):
    return [row[0] for row in conn.execute(FILES_WAITING).fetchall()]


def carry_files(client, conn, case_id, channel_id=None):
    sent = 0
    for message_id, forwarded_ts, anonymous, reporter, stored in conn.execute(
        FILES_ON_CASE, (case_id,)
    ).fetchall():
        try:
            carried = attachments.share(
                client, conn, message_id, room_of(stored, channel_id, conn), forwarded_ts,
                wearing=as_reporter(client, anonymous, reporter),
            )
        except Exception as failure:
            log.warning("nemo: message %s's file would not carry: %s", message_id, failure)
            continue
        if carried:
            sent += 1
    return sent


def waiting_follow_ups(conn):
    return [row[0] for row in conn.execute(FOLLOW_UPS_ANYWHERE).fetchall()]


def unannounced_reopens(conn):
    return [row[0] for row in conn.execute(UNANNOUNCED_REOPENS).fetchall()]


def carry_follow_ups(client, conn, case_id, channel_id=None):
    carried = 0
    for (message_id,) in conn.execute(FOLLOW_UPS_WAITING, (case_id,)).fetchall():
        try:
            landed = post_follow_up(client, conn, message_id, channel_id)
        except Exception as failure:
            log.warning("nemo: message %s would not carry: %s", message_id, failure)
            continue
        if landed:
            carried += 1
    return carried


def post_reopen_notice(client, conn, case_id, channel_id=None):
    row = conn.execute(WOKE, (case_id,)).fetchone()
    if row is None:
        return None

    was = row[0]
    found = post_reopen_announcement(client, conn, case_id, was, channel_id)
    conn.execute(REOPEN_ANNOUNCED, (case_id,))
    return found


def post_reopen_announcement(client, conn, case_id, was, channel_id=None):
    refresh_card(client, conn, case_id, channel_id)

    case = gather(conn, case_id)
    if case is None or not case["forwarded_ts"]:
        return None

    label = views.resolve.label(was) if was else "Resolved"
    return client.chat_postMessage(
        channel=card_channel(case, channel_id, conn),
        thread_ts=case["forwarded_ts"],
        text=views.lines.reopened_by_reporter(case_id, label),
        unfurl_links=False,
    )["ts"]


def echo(client, thread_ts, sent_by, body, signed, channel_id=None):
    seen = profile.profile(client, sent_by)
    wearing = {"username": seen["name"]}
    if seen["icon"]:
        wearing["icon_url"] = seen["icon"]
    wearing["metadata"] = {
        "event_type": "nemo_message",
        "event_payload": {"source_user_id": sent_by},
    }

    text = f"{answer.PREFIX}{views.report.escape_but_mentions(body)}"
    if not signed:
        text = f"{answer.ANON}{text}"

    room = channel_id or internal_log_channel()
    try:
        sent = client.chat_postMessage(
            channel=room,
            thread_ts=thread_ts,
            text=text,
            unfurl_links=False,
            unfurl_media=False,
            **wearing,
        )
    except Exception as failure:
        log.warning("nemo: the thread did not hear about the reply: %s", failure)
        return None

    return room, sent["ts"]


def mirror(client, conn, case_id, channel_id=None):
    room = card_room(conn, case_id, channel_id)
    carried = 0

    for chat_id, author, body, thread_ts in chat.waiting(conn, case_id):
        seen = profile.profile(client, author)
        wearing = {"username": seen["name"]}
        if seen["icon"]:
            wearing["icon_url"] = seen["icon"]
        wearing["metadata"] = {
            "event_type": "nemo_message",
            "event_payload": {"source_user_id": author},
        }

        try:
            sent = client.chat_postMessage(
                channel=room,
                thread_ts=thread_ts,
                text=views.report.escape_but_mentions(body),
                unfurl_links=False,
                unfurl_media=False,
                **wearing,
            )
        except Exception as failure:
            log.warning("nemo: chat %s did not reach the thread: %s", chat_id, failure)
            continue

        chat.mirrored(conn, chat_id, sent["ts"])
        carried += 1

    if carried:
        log.info("nemo: carried %s message(s) into case %s's thread", carried, case_id)
    return carried


KEEP_ECHO = """
INSERT INTO fd.case_chat
    (case_id, author_user_id, blocks, channel_id, ts, mirrored_ts, mirrored_at, mirrored_as,
     source_app)
VALUES (%s, %s, %s, %s, %s, %s, now(), 'nemo', 'nemo')
RETURNING id
"""


def post_echo(client, conn, case_id, blocks, by, fallback_text, trouble):
    thread_ts = thread_for(conn, case_id)
    if thread_ts is None:
        log.info("nemo: case %s has no thread yet, the echo has nowhere to go", case_id)
        return None

    room = card_room(conn, case_id)
    seen = profile.profile(client, by)
    wearing = {"username": seen["name"]}
    if seen["icon"]:
        wearing["icon_url"] = seen["icon"]
    wearing["metadata"] = {
        "event_type": "nemo_message",
        "event_payload": {"source_user_id": by},
    }

    try:
        sent = client.chat_postMessage(
            channel=room,
            thread_ts=thread_ts,
            blocks=blocks,
            text=fallback_text,
            unfurl_links=False,
            unfurl_media=False,
            **wearing,
        )
    except Exception as failure:
        log.warning(trouble, case_id, failure)
        return None

    conn.execute(KEEP_ECHO, (case_id, by, Jsonb(blocks), room, sent["ts"], sent["ts"]))
    return sent["ts"]


CHANNEL_NAME = "SELECT name FROM raw.channel_dim WHERE channel_id = %s"


def channel_name(conn, channel_id):
    row = conn.execute(CHANNEL_NAME, (channel_id,)).fetchone()
    return row[0] if row else None


def post_action_echo(client, conn, case_id, values, by):
    named = channel_name(conn, values["channel_id"]) if values.get("channel_id") else None
    blocks = views.action.echo_blocks(values, by, channel_name=named)
    return post_echo(client, conn, case_id, blocks, by, views.action.label(values["type_key"]),
        "nemo: the action log for case %s did not reach the thread: %s")


def post_resolution_echo(client, conn, case_id, resolution, member_note, by, actions=()):
    blocks = views.resolve.echo_blocks(resolution, member_note, by, actions, case_id)
    return post_echo(client, conn, case_id, blocks, by, views.resolve.label(resolution),
        "nemo: the resolution log for case %s did not reach the thread: %s")
