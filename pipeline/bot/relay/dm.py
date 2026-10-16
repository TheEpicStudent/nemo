import logging

from bot.core import blobs, intake, session
from bot.relay import consent, file_notices, intake_files
from bot.relay.reply import RECEIVED_REACTION, REPORTER_DELETE, nemo_delayed, receipt, submit_failed

log = logging.getLogger("bot.relay")

CONTENT_SUBTYPES = (None, "file_share", "me_message", "thread_broadcast")

DECLINED_BY = "relay:reporter declined"

CONVERSATION_STATE = """
SELECT c.handed_off_at IS NOT NULL,
       (SELECT m.ts FROM fd.intake_messages m
        WHERE m.conversation_id = c.id AND m.direction = 'outbound'
          AND m.subtype = %s AND m.deleted_at IS NULL
        ORDER BY m.posted_at DESC LIMIT 1),
       c.consent_choice
FROM fd.intake_conversations c
WHERE c.id = %s
"""

INBOUND_BODIES = """
SELECT body
FROM fd.intake_messages
WHERE conversation_id = %s AND direction = 'inbound' AND deleted_at IS NULL
ORDER BY posted_at, id
"""

FILE_COUNT = """
SELECT count(*)
FROM fd.intake_message_files f
JOIN fd.intake_messages m ON m.id = f.message_id
WHERE m.conversation_id = %s
"""

FORWARDED_SOURCE_CHANNELS = """
SELECT s.source_channel_name
FROM fd.intake_shares s
JOIN fd.intake_messages m ON m.id = s.message_id
WHERE m.conversation_id = %s AND m.direction = 'inbound' AND s.kind = 'forward'
ORDER BY s.id
"""

CONVERSATION_BY_MESSAGE = """
SELECT conversation_id FROM fd.intake_messages WHERE channel_id = %s AND ts = %s
"""

LATEST_INBOUND_MESSAGE = """
SELECT id FROM fd.intake_messages
WHERE conversation_id = %s AND direction = 'inbound'
ORDER BY posted_at DESC, id DESC LIMIT 1
"""

SET_PROMPT_SUBTYPE = """
UPDATE fd.intake_messages SET subtype = %s, last_seen_at = now()
WHERE channel_id = %s AND ts = %s
"""

STORE_CONSENT_CHOICE = """
UPDATE fd.intake_conversations SET consent_choice = %s
WHERE id = %s AND handed_off_at IS NULL
"""

CLEAR_CONSENT_CHOICE = """
UPDATE fd.intake_conversations SET consent_choice = NULL WHERE id = %s
"""

SUBMITTED_INBOUND = """
SELECT 1 FROM fd.intake_messages m
JOIN fd.intake_conversations c ON c.id = m.conversation_id
WHERE m.id = %s AND m.direction = 'inbound' AND c.handed_off_at IS NOT NULL AND c.closed_at IS NULL
"""

TRUSTED_SENDERS = "SELECT value FROM fd.app_settings WHERE key = 'relay.trusted_senders'"

HANDED_OFF = "SELECT handed_off_at IS NOT NULL FROM fd.intake_conversations WHERE id = %s"


def trusted_senders(conn):
    row = conn.execute(TRUSTED_SENDERS).fetchone()
    return {one.strip() for one in (row[0] if row else "").split(",") if one.strip()}


def preview(conn, conversation_id, saved_choice=None):
    bodies = [row[0] for row in conn.execute(INBOUND_BODIES, (conversation_id,)).fetchall()]
    file_count = conn.execute(FILE_COUNT, (conversation_id,)).fetchone()[0]
    forwarded = conn.execute(FORWARDED_SOURCE_CHANNELS, (conversation_id,)).fetchall()
    return consent.build_blocks(bodies, file_count, [row[0] for row in forwarded], saved_choice)


def register(app, on_submit=None):
    @app.event("message")
    def on_message(event, client):
        if event.get("channel_type") != "im":
            return

        subtype = event.get("subtype")
        if subtype == "message_changed":
            return on_changed(event, client)
        if subtype == "message_deleted":
            return on_deleted(event, client)
        if subtype not in CONTENT_SUBTYPES:
            return
        with session() as conn:
            trusted = event.get("user") in trusted_senders(conn)
        if trusted:
            return submit_trusted(event, client)
        if event.get("bot_id"):
            return

        thread_ts = intake.root_ts(event)

        with session() as conn:
            message_id, inserted = intake.record(conn, event)
            conversation_id = intake.conversation(conn, event["channel"], thread_ts)
            intake.rename_anonymous_files(conn, conversation_id)
            handed_off, prompt_ts, saved_choice = conn.execute(
                CONVERSATION_STATE, (consent.SUBTYPE, conversation_id)
            ).fetchone()
            prompt_blocks = None if handed_off else preview(conn, conversation_id, saved_choice)

        if not inserted:
            return
        log.info(
            "relay: took message %s in %s thread %s", message_id, event["channel"], thread_ts
        )

        if handed_off:
            if event.get("files"):
                fetch_files(client)
            react_received(client, event["channel"], event["ts"])
            if on_submit:
                on_submit(conversation_id, message_id)
            return

        post_prompt(client, event["channel"], thread_ts, prompt_ts, prompt_blocks)

    def submit_trusted(event, client):
        with session() as conn:
            message_id, inserted = intake.record(conn, event)
            conversation_id = intake.conversation(conn, event["channel"], intake.root_ts(event))
            handed_off = conn.execute(HANDED_OFF, (conversation_id,)).fetchone()[0]
        if not inserted or handed_off:
            return None
        if on_submit is None:
            log.error("relay: nobody is taking reports, trusted conversation %s waits", conversation_id)
            return None

        try:
            case_id = on_submit(conversation_id, message_id, False)
        except Exception:
            log.exception("relay: trusted conversation %s could not be handed over", conversation_id)
            return None
        with session() as conn:
            intake.close(conn, conversation_id, intake.TRUSTED_SENDER)
        react_received(client, event["channel"], event["ts"])
        log.info("relay: trusted sender %s opened case %s", event.get("user"), case_id)
        return case_id

    def fetch_files(client):
        try:
            stored = intake_files.drain(client.token)
        except Exception:
            log.exception("relay: could not keep the files, they stay pending")
            stored = 0
        try:
            file_notices.post_notices(client)
        except Exception:
            log.exception("relay: could not tell reporters about files that were not sent")
        return stored

    def post_prompt(client, channel_id, thread_ts, prompt_ts, blocks):
        if prompt_ts:
            client.chat_update(
                channel=channel_id, ts=prompt_ts, text=consent.FALLBACK, blocks=blocks
            )
            return

        sent = client.chat_postMessage(
            channel=channel_id,
            thread_ts=thread_ts,
            text=consent.FALLBACK,
            blocks=blocks,
        )
        with session() as conn:
            intake.record(
                conn,
                {
                    "channel": channel_id,
                    "ts": sent["ts"],
                    "thread_ts": thread_ts,
                    "text": consent.FALLBACK,
                    "blocks": blocks,
                    "subtype": consent.SUBTYPE,
                },
                direction="outbound",
            )

    def react_received(client, channel_id, ts):
        try:
            client.reactions_add(channel=channel_id, timestamp=ts, name=RECEIVED_REACTION)
        except Exception as failure:
            log.warning("relay: could not tick their message: %s", failure)

    @app.action(consent.ACTION)
    def on_identity_action(ack, body):
        ack()
        choice = consent.submitted_values(body.get("state"))
        if not choice:
            return

        with session() as conn:
            row = conn.execute(
                CONVERSATION_BY_MESSAGE, (body["channel"]["id"], body["message"]["ts"])
            ).fetchone()
            if not row:
                return
            conn.execute(STORE_CONSENT_CHOICE, (choice, row[0]))

    @app.action(consent.CONFIRM)
    def on_confirm(ack, body, client):
        ack()
        channel_id = body["channel"]["id"]
        prompt_ts = body["message"]["ts"]

        with session() as conn:
            row = conn.execute(CONVERSATION_BY_MESSAGE, (channel_id, prompt_ts)).fetchone()
            if not row:
                return
            conversation_id = row[0]
            handed_off, _, saved_choice = conn.execute(
                CONVERSATION_STATE, (consent.SUBTYPE, conversation_id)
            ).fetchone()
            message_id = conn.execute(LATEST_INBOUND_MESSAGE, (conversation_id,)).fetchone()[0]

        anonymous = consent.resolve_choice(body.get("state"), saved_choice) == consent.ANONYMOUS

        if handed_off:
            client.chat_update(
                channel=channel_id, ts=prompt_ts, text=consent.ALREADY_SENT, blocks=[]
            )
            return

        if on_submit is None:
            log.error(
                "relay: nobody is taking reports, conversation %s stays with the reporter",
                conversation_id,
            )
            text, blocks = submit_failed()
            client.chat_update(channel=channel_id, ts=prompt_ts, text=text, blocks=blocks)
            return

        with session() as conn:
            conn.execute(SET_PROMPT_SUBTYPE, (consent.DONE, channel_id, prompt_ts))
            conn.execute(CLEAR_CONSENT_CHOICE, (conversation_id,))

        log.info(
            "relay: conversation %s handed over, anonymous=%s", conversation_id, anonymous
        )
        try:
            case_id = on_submit(conversation_id, message_id, anonymous)
        except Exception:
            log.exception(
                "relay: conversation %s could not be handed over, telling them to try again",
                conversation_id,
            )
            text, blocks = submit_failed()
            client.chat_update(channel=channel_id, ts=prompt_ts, text=text, blocks=blocks)
            return

        with session() as conn:
            delayed = nemo_delayed(conn)

        text, blocks = receipt(case_id, anonymous, delayed)
        client.chat_update(channel=channel_id, ts=prompt_ts, text=text, blocks=blocks)

    @app.action(consent.CANCEL)
    def on_cancel(ack, body, client):
        ack()
        channel_id = body["channel"]["id"]
        prompt_ts = body["message"]["ts"]

        with session() as conn:
            conn.execute(SET_PROMPT_SUBTYPE, (consent.DONE, channel_id, prompt_ts))
            row = conn.execute(CONVERSATION_BY_MESSAGE, (channel_id, prompt_ts)).fetchone()
            if row:
                purged, removed = blobs.purge_conversation(conn, row[0], DECLINED_BY)
                if purged:
                    log.info(
                        "relay: conversation %s was declined, %s file(s) purged, "
                        "%s blob(s) removed", row[0], purged, removed,
                    )

        client.chat_update(
            channel=channel_id, ts=prompt_ts, text=consent.CANCELLED, blocks=[]
        )

    def on_changed(event, client):
        message = event.get("message") or {}
        if not message.get("ts"):
            return
        with session() as conn:
            changed = intake.edit(conn, event["channel"], message)
            if not changed:
                return
            row = conn.execute(
                CONVERSATION_BY_MESSAGE, (event["channel"], message["ts"])
            ).fetchone()
            if not row:
                log.warning("relay: edited message %s has no conversation", changed)
                return
            conversation_id = row[0]
            handed_off, prompt_ts, saved_choice = conn.execute(
                CONVERSATION_STATE, (consent.SUBTYPE, conversation_id)
            ).fetchone()
            prompt_blocks = None if handed_off else preview(conn, conversation_id, saved_choice)

        log.info("relay: message %s was edited", changed)
        if prompt_ts and prompt_blocks:
            client.chat_update(
                channel=event["channel"], ts=prompt_ts, text=consent.FALLBACK, blocks=prompt_blocks
            )

    def on_deleted(event, client):
        if not event.get("deleted_ts"):
            return
        with session() as conn:
            deleted_id = intake.delete(conn, event["channel"], event["deleted_ts"])
            reported = conn.execute(SUBMITTED_INBOUND, (deleted_id,)).fetchone() if deleted_id else None
        if deleted_id:
            log.info("relay: message %s was deleted", deleted_id)
        previous = event.get("previous_message") or {}
        if reported and previous.get("user"):
            try:
                client.chat_postEphemeral(channel=event["channel"], user=previous["user"],
                                          thread_ts=previous.get("thread_ts"), text=REPORTER_DELETE)
            except Exception as failure:
                log.warning("relay: could not say the deletion was not forwarded: %s", failure)
