import logging

from bot.core import blobs, intake, session
from bot.relay import reply

log = logging.getLogger("bot.relay")

SUBTYPE = "file_notice"

UNNOTIFIED_FILES = """
SELECT DISTINCT ON (f.id) f.id, c.channel_id, c.thread_ts, f.fetch_state, f.fetch_error,
       coalesce(
           jsonb_path_query_first(m.raw, '$.** ? (@.id == $id).name',
                                  jsonb_build_object('id', f.slack_file_id)) #>> '{}',
           f.name
       )
FROM fd.intake_files f
JOIN fd.intake_message_files mf ON mf.file_id = f.id
JOIN fd.intake_messages m ON m.id = mf.message_id
JOIN fd.intake_conversations c ON c.id = m.conversation_id
WHERE f.reporter_notified_at IS NULL
  AND (f.fetch_state IN ('too_large', 'refused', 'failed') OR (f.fetch_state = 'skipped' AND f.is_external))
  AND m.direction = 'inbound' AND c.handed_off_at IS NOT NULL AND c.closed_at IS NULL
ORDER BY f.id, m.posted_at
LIMIT %s
"""

CLAIM = """
UPDATE fd.intake_files SET reporter_notified_at = now()
WHERE id = %s AND reporter_notified_at IS NULL
RETURNING id
"""

RELEASE = "UPDATE fd.intake_files SET reporter_notified_at = NULL WHERE id = %s"


def notice_text(state, error, name):
    if state == "too_large":
        return reply.file_too_large(name, blobs.cap())
    if state == "refused" and error == blobs.NOT_MEDIA:
        return reply.file_not_media(name)
    if state == "refused" and error == blobs.PDF_ACTIVE_CONTENT:
        return reply.file_active_content(name)
    if state == "refused" and error == blobs.PDF_ENCRYPTED:
        return reply.file_encrypted(name)
    if state == "skipped":
        return reply.file_external(name)
    return reply.file_not_downloaded(name)


def post_notices(client, limit=50):
    with session() as conn:
        rows = conn.execute(UNNOTIFIED_FILES, (limit,)).fetchall()

    sent = 0
    for file_id, channel_id, thread_ts, state, error, name in rows:
        with session() as conn:
            if conn.execute(CLAIM, (file_id,)).fetchone() is None:
                continue
        text = notice_text(state, error, name)
        try:
            posted = client.chat_postMessage(channel=channel_id, thread_ts=thread_ts, text=text)
        except Exception as failure:
            log.warning("relay: could not tell the reporter about file %s: %s", file_id, failure)
            with session() as conn:
                conn.execute(RELEASE, (file_id,))
            continue
        with session() as conn:
            intake.record(conn, {"channel": channel_id, "ts": posted["ts"], "thread_ts": thread_ts,
                                 "text": text, "subtype": SUBTYPE}, direction="outbound")
        sent += 1
        log.info("relay: told the reporter file %s was not sent (%s)", file_id, state)
    return sent
