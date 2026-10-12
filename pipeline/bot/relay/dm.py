import logging

from bot.core import blobs, intake, session
from bot.relay import consent, intake_files
from bot.relay.reply import GOT_IT, nemo_is_behind, handoff_failed, receipt

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

HOW_MANY_FILES = """
SELECT count(*)
FROM fd.intake_message_files f
JOIN fd.intake_messages m ON m.id = f.message_id
WHERE m.conversation_id = %s
"""

WHAT_THEY_FORWARDED = """
SELECT s.source_channel_name
FROM fd.intake_shares s
JOIN fd.intake_messages m ON m.id = s.message_id
WHERE m.conversation_id = %s AND m.direction = 'inbound' AND s.kind = 'forward'
ORDER BY s.id
"""

CONVERSATION_OF = """
SELECT conversation_id FROM fd.intake_messages WHERE channel_id = %s AND ts = %s
"""

NEWEST_INBOUND = """
SELECT id FROM fd.intake_messages
WHERE conversation_id = %s AND direction = 'inbound'
ORDER BY posted_at DESC, id DESC LIMIT 1
"""

RETIRE_PROMPT = """
UPDATE fd.intake_messages SET subtype = %s, last_seen_at = now()
WHERE channel_id = %s AND ts = %s
"""

REMEMBER_CHOICE = """
UPDATE fd.intake_conversations SET consent_choice = %s
WHERE id = %s AND handed_off_at IS NULL
"""

FORGET_CHOICE = """
UPDATE fd.intake_conversations SET consent_choice = NULL WHERE id = %s
"""


def preview(conn, conversation_id, saved_choice=None):
    bodies = [row[0] for row in conn.execute(INBOUND_BODIES, (conversation_id,)).fetchall()]
    file_count = conn.execute(HOW_MANY_FILES, (conversation_id,)).fetchone()[0]
    forwarded = conn.execute(WHAT_THEY_FORWARDED, (conversation_id,)).fetchall()
    return consent.build_blocks(bodies, file_count, [row[0] for row in forwarded], saved_choice)


def register(app, on_handoff=None):
    @app.event("message")
    def on_message(event, client):
        if event.get("channel_type") != "im":
            return

        subtype = event.get("subtype")
        if subtype == "message_changed":
            return on_changed(event, client)
        if subtype == "message_deleted":
            return on_deleted(event)
        if subtype not in CONTENT_SUBTYPES:
            return
        if event.get("bot_id"):
            return

        thread_ts = intake.root_ts(event)

        with session() as conn:
            message_id, inserted = intake.record(conn, event)
            conversation_id = intake.conversation(conn, event["channel"], thread_ts)
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
            acknowledge(client, event["channel"], event["ts"])
            if on_handoff:
                on_handoff(conversation_id, message_id)
            return

        post_prompt(client, event["channel"], thread_ts, prompt_ts, prompt_blocks)

    def fetch_files(client):
        try:
            return intake_files.drain(client.token)
        except Exception:
            log.exception("relay: could not keep the files, they stay pending")
            return 0

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

    def acknowledge(client, channel_id, ts):
        try:
            client.reactions_add(channel=channel_id, timestamp=ts, name=GOT_IT)
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
                CONVERSATION_OF, (body["channel"]["id"], body["message"]["ts"])
            ).fetchone()
            if not row:
                return
            conn.execute(REMEMBER_CHOICE, (choice, row[0]))

    @app.action(consent.CONFIRM)
    def on_confirm(ack, body, client):
        ack()
        channel_id = body["channel"]["id"]
        prompt_ts = body["message"]["ts"]

        with session() as conn:
            row = conn.execute(CONVERSATION_OF, (channel_id, prompt_ts)).fetchone()
            if not row:
                return
            conversation_id = row[0]
            handed_off, _, saved_choice = conn.execute(
                CONVERSATION_STATE, (consent.SUBTYPE, conversation_id)
            ).fetchone()
            message_id = conn.execute(NEWEST_INBOUND, (conversation_id,)).fetchone()[0]

        anonymous = consent.resolve_choice(body.get("state"), saved_choice) == consent.ANONYMOUS

        if handed_off:
            client.chat_update(
                channel=channel_id, ts=prompt_ts, text=consent.ALREADY, blocks=[]
            )
            return

        if on_handoff is None:
            log.error(
                "relay: nobody is taking reports, conversation %s stays with the reporter",
                conversation_id,
            )
            text, blocks = handoff_failed()
            client.chat_update(channel=channel_id, ts=prompt_ts, text=text, blocks=blocks)
            return

        with session() as conn:
            conn.execute(RETIRE_PROMPT, (consent.DONE, channel_id, prompt_ts))
            conn.execute(FORGET_CHOICE, (conversation_id,))

        log.info(
            "relay: conversation %s handed over, anonymous=%s", conversation_id, anonymous
        )
        try:
            case_id = on_handoff(conversation_id, message_id, anonymous)
        except Exception:
            log.exception(
                "relay: conversation %s could not be handed over, telling them to try again",
                conversation_id,
            )
            text, blocks = handoff_failed()
            client.chat_update(channel=channel_id, ts=prompt_ts, text=text, blocks=blocks)
            return

        with session() as conn:
            behind = nemo_is_behind(conn)

        text, blocks = receipt(case_id, anonymous, behind)
        client.chat_update(channel=channel_id, ts=prompt_ts, text=text, blocks=blocks)

    @app.action(consent.CANCEL)
    def on_cancel(ack, body, client):
        ack()
        channel_id = body["channel"]["id"]
        prompt_ts = body["message"]["ts"]

        with session() as conn:
            conn.execute(RETIRE_PROMPT, (consent.DONE, channel_id, prompt_ts))
            row = conn.execute(CONVERSATION_OF, (channel_id, prompt_ts)).fetchone()
            if row:
                dropped, removed = blobs.purge_conversation(conn, row[0], DECLINED_BY)
                if dropped:
                    log.info(
                        "relay: conversation %s was declined, %s file(s) purged, "
                        "%s blob(s) removed", row[0], dropped, removed,
                    )

        client.chat_update(
            channel=channel_id, ts=prompt_ts, text=consent.DROPPED, blocks=[]
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
                CONVERSATION_OF, (event["channel"], message["ts"])
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

    def on_deleted(event):
        if not event.get("deleted_ts"):
            return
        with session() as conn:
            deleted_id = intake.delete(conn, event["channel"], event["deleted_ts"])
        if deleted_id:
            log.info("relay: message %s was deleted", deleted_id)
