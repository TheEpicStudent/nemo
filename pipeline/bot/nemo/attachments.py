import logging

from bot.core import blobs, slack_files

INLINE_MIMETYPES = ("image/png", "image/jpeg", "image/jpg", "image/gif")
FILE_INDEX_DELAY = 1.0

log = logging.getLogger("bot.nemo")

UNMIRRORED_FILES = """
SELECT mf.file_id, f.name, f.stored_key
FROM fd.intake_message_files mf
JOIN fd.intake_files f ON f.id = mf.file_id
WHERE mf.message_id = %s AND mf.mirrored_at IS NULL AND f.fetch_state = 'stored'
  AND NOT mf.forwarded
ORDER BY mf.seq
"""

MARK_MIRRORED = """
UPDATE fd.intake_message_files SET mirrored_file_id = %s, mirrored_at = now()
WHERE message_id = %s AND file_id = %s AND mirrored_at IS NULL
"""


def shows_inline(mimetype):
    return (mimetype or "").lower() in INLINE_MIMETYPES


def upload_file(client, name, body, channel_id=None, thread_ts=None):
    where = {"channel": channel_id, "thread_ts": thread_ts} if channel_id else {}
    response = client.files_upload_v2(content=body, filename=name, title=name, **where)
    return (response.get("files") or [{}])[0].get("id")


def collect_unmirrored_files(conn, message_id):
    files = []
    for file_id, name, sha in conn.execute(UNMIRRORED_FILES, (message_id,)).fetchall():
        body, _ = blobs.body_of(conn, sha)
        if body is None:
            log.warning("nemo: file %s says stored but has no bytes", file_id)
            continue
        files.append((file_id, name or f"{sha[:12]}", body))
    return files


def share(client, conn, message_id, channel_id, thread_ts, author_fields=None, body=None,
          unfurl=True, summary=False):
    files = collect_unmirrored_files(conn, message_id)
    text = (body or "").strip() or (attachment_summary(files) if summary and files else "")
    if not files and not text:
        return None

    ts = post_text(client, channel_id, thread_ts, text, author_fields or {}, unfurl) if text else None
    for file_id, name, file_body in files:
        try:
            uploaded = upload_file(client, name, file_body, channel_id, thread_ts)
        except Exception:
            log.exception("nemo: could not carry file %s into the thread", file_id)
            continue
        if uploaded:
            conn.execute(MARK_MIRRORED, (uploaded, message_id, file_id))
    return ts


def post_text(client, channel_id, thread_ts, text, author_fields, unfurl=True):
    sent = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=text,
        unfurl_links=unfurl,
        unfurl_media=unfurl,
        **author_fields,
    )
    return sent["ts"]


def attachment_summary(files):
    if len(files) == 1:
        return files[0][1]
    return f"{len(files)} attachments"


def fetch(url, token, limit):
    body, state, error = slack_files.download(url, token, limit)
    if state != "stored":
        log.warning("nemo: could not fetch a file: %s %s", state, error or "")
        return None
    return body
