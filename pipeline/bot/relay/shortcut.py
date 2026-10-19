import logging
from decimal import Decimal

from bot.core import case, intake, session
from bot.core.formatting import quote_text
from bot.relay import consent
from bot.relay.reply import SENDING, SUBMIT_FAILED, nemo_delayed, receipt

log = logging.getLogger("bot.relay")

REPORT_ANONYMOUS = "report_anonymous"
REPORT_WITH_NAME = "report_with_name"

ARCHIVES = "https://hackclub.slack.com/archives"
NO_TEXT = "(no text)"
NOT_REPORTABLE = "That message cannot be reported."
REPORTED = "Report sent. Replies arrive in a DM thread."

MEMBER = "member"
BOT = "bot"
WITHHELD = "withheld"

MICROSECOND = Decimal("0.000001")


def message_link(channel_id, ts, thread_ts=None):
    base = f"{ARCHIVES}/{channel_id}/p{ts.replace('.', '')}"
    if thread_ts and thread_ts != ts:
        return f"{base}?thread_ts={thread_ts}&cid={channel_id}"
    return base


def is_bot_post(message):
    return bool(message.get("bot_id")) or message.get("subtype") == "bot_message"


def author_is_bot(client, message):
    if not is_bot_post(message):
        return False
    try:
        info = client.users_info(user=message["user"])["user"]
    except Exception as failure:
        log.info("relay: could not tell whether %s is a bot: %s", message.get("user"), failure)
        return True
    return bool(info.get("is_bot") or info.get("is_app_user"))


def source_author(client, message, reporter_id, anonymous):
    author_id = message.get("user")
    if not author_id or author_is_bot(client, message):
        return None, BOT
    if author_id == reporter_id and anonymous:
        return None, WITHHELD
    return author_id, MEMBER


def forwarded_attachment(body, message, author_id, author_kind, text):
    origin = body["channel"]["id"]
    url = message_link(origin, message["ts"], message.get("thread_ts"))
    return {
        "is_share": True,
        "channel_id": origin,
        "channel_name": body["channel"].get("name"),
        "ts": message["ts"],
        "thread_ts": message.get("thread_ts"),
        "author_id": author_id,
        "author_kind": author_kind,
        "text": text,
        "fallback": text,
        "from_url": url,
        "files": message.get("files"),
    }


def inbound_event(dm_channel, root_ts, reporter_id, message, attachment, text):
    return {
        "channel": dm_channel,
        "ts": str(Decimal(root_ts) + MICROSECOND),
        "thread_ts": root_ts,
        "user": reporter_id,
        "text": text,
        "blocks": message.get("blocks"),
        "attachments": [attachment],
    }


def root_event(dm_channel, root_ts, blocks):
    return {"channel": dm_channel, "ts": root_ts, "text": SENDING, "blocks": blocks, "subtype": consent.DONE}


def section(text):
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def tell(respond, text):
    try:
        respond(text=text, response_type="ephemeral")
    except Exception as failure:
        log.warning("relay: could not answer the shortcut: %s", failure)


def open_thread(client, reporter_id):
    dm_channel = client.conversations_open(users=reporter_id)["channel"]["id"]
    sent = client.chat_postMessage(channel=dm_channel, text=SENDING, blocks=section(SENDING))
    return dm_channel, sent["ts"]


def record_report(dm_channel, root_ts, reporter_id, event):
    with session() as conn:
        conversation_id = intake.conversation(conn, dm_channel, root_ts, reporter_id)
        intake.record(conn, root_event(dm_channel, root_ts, section(SENDING)), direction="outbound")
        message_id, _inserted = intake.record(conn, event)
    return conversation_id, message_id


def show_receipt(client, dm_channel, root_ts, case_id, anonymous):
    with session() as conn:
        delayed = nemo_delayed(conn)
    text, blocks = receipt(case_id, anonymous, delayed)
    client.chat_update(channel=dm_channel, ts=root_ts, text=text, blocks=blocks)


def show_failure(client, dm_channel, root_ts):
    try:
        client.chat_update(channel=dm_channel, ts=root_ts, text=SUBMIT_FAILED, blocks=section(SUBMIT_FAILED))
    except Exception as failure:
        log.warning("relay: could not mark the report as not sent: %s", failure)


def file_report(body, client, respond, anonymous, on_submit):
    reporter_id = (body.get("user") or {}).get("id")
    message = body.get("message") or {}
    origin = (body.get("channel") or {}).get("id")
    if not (reporter_id and origin and message.get("ts")):
        return tell(respond, NOT_REPORTABLE)
    if on_submit is None:
        log.error("relay: nobody is taking reports, the shortcut from %s is dropped", reporter_id)
        return tell(respond, SUBMIT_FAILED)

    text = quote_text(message.get("text")) or NO_TEXT
    author_id, author_kind = source_author(client, message, reporter_id, anonymous)
    attachment = forwarded_attachment(body, message, author_id, author_kind, text)

    try:
        dm_channel, root_ts = open_thread(client, reporter_id)
        event = inbound_event(dm_channel, root_ts, reporter_id, message, attachment, text)
        conversation_id, message_id = record_report(dm_channel, root_ts, reporter_id, event)
    except Exception:
        log.exception("relay: could not start a report for %s", reporter_id)
        return tell(respond, SUBMIT_FAILED)

    subject_id = author_id if author_id != reporter_id else None
    try:
        case_id = on_submit(conversation_id, message_id, anonymous, subject_user_id=subject_id,
                            entry_point=case.SHORTCUT)
    except Exception:
        log.exception("relay: report %s from %s could not be handed over", conversation_id, reporter_id)
        show_failure(client, dm_channel, root_ts)
        return tell(respond, SUBMIT_FAILED)

    try:
        show_receipt(client, dm_channel, root_ts, case_id, anonymous)
    except Exception:
        log.exception("relay: case %s has no receipt in %s", case_id, dm_channel)

    log.info("relay: %s reported %s in %s as case %s, anonymous=%s",
             reporter_id, message["ts"], origin, case_id, anonymous)
    return tell(respond, REPORTED)


def register(app, on_submit=None):
    @app.shortcut(REPORT_ANONYMOUS)
    def on_report_anonymous(ack, body, client, respond):
        ack()
        file_report(body, client, respond, True, on_submit)

    @app.shortcut(REPORT_WITH_NAME)
    def on_report_with_name(ack, body, client, respond):
        ack()
        file_report(body, client, respond, False, on_submit)
