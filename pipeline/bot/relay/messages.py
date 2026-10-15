import logging

from bot.core import blobs, case, evidence, profiles, intake, outbox, session
from bot.core.whoami import bot_user_id
from bot.core.formatting import to_member
from bot.relay import intake_files

log = logging.getLogger("bot.relay")

LOOK_BACK = 30

INSERT_FILE = """
INSERT INTO fd.intake_files
    (slack_file_id, name, mimetype, original_w, original_h,
     fetch_state, sha256, stored_key, stored_bytes, fetched_at)
VALUES (%s, %s, %s, %s, %s, 'stored', %s, %s, %s, now())
ON CONFLICT (slack_file_id) DO UPDATE SET last_seen_at = now()
RETURNING id
"""

LINK_FILE = """
INSERT INTO fd.intake_message_files (message_id, file_id, seq, mirrored_file_id, mirrored_at)
VALUES (%s, %s, %s, %s, now())
ON CONFLICT DO NOTHING
"""

FIRST_ANSWER_FOR = """
UPDATE fd.case_reports SET first_replied_at = now()
WHERE id = (SELECT report_id FROM fd.intake_conversations WHERE id = %s)
  AND first_replied_at IS NULL
"""


def shared_at(file, channel_id):
    shares = (file or {}).get("shares") or {}
    for kind in ("public", "private"):
        for shared_channel_id, entries in (shares.get(kind) or {}).items():
            if shared_channel_id == channel_id and entries:
                return entries[0].get("ts")
    return None


class MessageRelay:
    def __init__(self, client=None):
        self.client = client

    def hand_off(self, conversation_id, message_id, anonymous=True):
        opener = bot_user_id(self.client, "relay")
        with session() as conn:
            already = case.existing(conn, conversation_id)
            case_id = case.open_case(conn, conversation_id, opener, anonymous)
            evidence_blocks = evidence.promote(conn, case_id, conversation_id, opener)
            if already:
                case.reopen(conn, case_id, opener)
        log.info("relay: conversation %s is case %s", conversation_id, case_id)
        self.fetch_attachments(conversation_id)
        if evidence_blocks["threads"] or evidence_blocks["messages"]:
            log.info(
                "relay: case %s came with %s thread(s) and %s message(s)",
                case_id, evidence_blocks["threads"], evidence_blocks["messages"],
            )

        return case_id

    def fetch_attachments(self, conversation_id):
        try:
            return intake_files.drain(self.client.token)
        except Exception:
            log.exception(
                "relay: could not keep the files of conversation %s, they stay pending",
                conversation_id,
            )
            return 0

    def deliver(self, conversation_id=None):
        with session() as conn:
            queue = outbox.waiting(conn, conversation_id)

        sent = 0
        for queued in queue:
            with session() as conn:
                if self.deliver_message(conn, queued):
                    sent += 1

        if sent:
            log.info("relay: sent %s queued message(s)", sent)

        return sent

    def deliver_message(self, conn, queued):
        if queued.closed_at:
            outbox.mark_error(conn, queued.id, "the reporter's conversation is closed", True)
            log.info("relay: outbox %s is for a closed conversation", queued.id)
            return False

        words = (queued.body or "").strip()
        files = queued.files or []
        if not words and not files:
            outbox.mark_error(conn, queued.id, "the message was empty", True)
            log.warning("relay: outbox %s had neither words nor a file", queued.id)
            return False

        try:
            message_ts = self.post_message(queued) if words else None
            uploaded = self.upload_files(conn, queued)
        except Exception as failure:
            outbox.mark_error(conn, queued.id, failure, queued.last_try)
            log.warning("relay: outbox %s did not go: %s", queued.id, failure)
            return False

        if words and message_ts is None:
            outbox.mark_error(conn, queued.id, "Slack returned no message ID", True)
            return False

        ts = message_ts or next((one["ts"] for one in uploaded if one.get("ts")), None)
        if ts is None:
            log.info("relay: slack named no message for outbox %s, keeping it anyway", queued.id)

        message_id, _ = intake.record(
            conn,
            {
                "channel": queued.channel_id,
                "ts": ts,
                "thread_ts": queued.thread_ts,
                "text": queued.body,
            },
            direction="outbound",
            sent_by=queued.requested_by,
        )
        self.store_sent_files(conn, message_id, uploaded)
        outbox.sent(conn, queued.id, message_id)
        if queued.kind == "reply":
            conn.execute(FIRST_ANSWER_FOR, (queued.conversation_id,))
        return True

    def post_message(self, queued):
        posted = self.client.chat_postMessage(
            channel=queued.channel_id,
            thread_ts=queued.thread_ts,
            text=to_member(queued.body),
            unfurl_links=False,
            unfurl_media=False,
            **self.display_identity(queued),
        )
        return posted.get("ts")

    def store_sent_files(self, conn, message_id, uploaded):
        for seq, one in enumerate(uploaded):
            file_id = conn.execute(
                INSERT_FILE,
                (one.get("id"), one.get("name"), one.get("mimetype"),
                 one.get("original_w"), one.get("original_h"),
                 one["sha256"], one["sha256"], one.get("size")),
            ).fetchone()[0]
            conn.execute(LINK_FILE, (message_id, file_id, seq, one.get("id") or "sent"))

    def upload_files(self, conn, queued):
        uploaded = []
        for one in queued.files or []:
            body, stored_type = blobs.body_of(conn, one.get("sha256"))
            if body is None:
                log.warning("relay: outbox %s lost the bytes of %s", queued.id, one.get("name"))
                continue

            response = self.client.files_upload_v2(
                channel=queued.channel_id,
                thread_ts=queued.thread_ts,
                content=body,
                filename=one.get("name") or "file",
            )
            sent = (response.get("files") or [{}])[0]
            uploaded.append({
                "sha256": one["sha256"],
                "name": one.get("name"),
                "mimetype": sent.get("mimetype") or one.get("mimetype") or stored_type,
                "original_w": one.get("original_w") or sent.get("original_w"),
                "original_h": one.get("original_h") or sent.get("original_h"),
                "size": len(body),
                "id": sent.get("id"),
                "ts": self.resolve_destination(sent, queued.channel_id, queued.thread_ts),
            })
        return uploaded

    def resolve_destination(self, file, channel_id, thread_ts):
        ts = shared_at(file, channel_id)
        if ts:
            return ts

        file_id = file.get("id")
        if not file_id:
            return None

        try:
            file_info = self.client.files_info(file=file_id)
            ts = shared_at(file_info.get("file"), channel_id)
            if ts:
                return ts
        except Exception as failure:
            log.info("relay: files.info would not place %s: %s", file_id, failure)

        return self.find_file_in_thread(file_id, channel_id, thread_ts)

    def find_file_in_thread(self, file_id, channel_id, thread_ts):
        try:
            response = self.client.conversations_replies(
                channel=channel_id, ts=thread_ts, limit=LOOK_BACK
            )
        except Exception as failure:
            log.warning("relay: could not read the thread to place %s: %s", file_id, failure)
            return None

        for message in reversed(response.get("messages") or []):
            for one in message.get("files") or []:
                if one.get("id") == file_id:
                    return message.get("ts")
        return None

    def display_identity(self, queued):
        if queued.mode != "signed" or not queued.requested_by:
            return {}

        return {
            "username": profiles.name(queued.requested_by) or f"@{queued.requested_by}",
            "icon_url": profiles.icon_url(queued.requested_by),
            "metadata": {
                "event_type": "nemo_message",
                "event_payload": {"source_user_id": queued.requested_by},
            },
        }
