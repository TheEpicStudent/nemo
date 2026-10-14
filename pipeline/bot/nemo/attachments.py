import logging
import time
import urllib.error
import urllib.request

from bot.core import blobs

TIMEOUT = 30
IN_BLOCKS = ("image/png", "image/jpeg", "image/jpg", "image/gif")
FILE_INDEX_DELAY = 1.0

log = logging.getLogger("bot.nemo")

TO_SHARE = """
SELECT mf.file_id, f.name, f.mimetype, f.stored_key, f.original_w
FROM fd.intake_message_files mf
JOIN fd.intake_files f ON f.id = mf.file_id
WHERE mf.message_id = %s AND mf.mirrored_at IS NULL AND f.fetch_state = 'stored'
  AND NOT mf.forwarded
ORDER BY mf.seq
"""

MIRRORED = """
UPDATE fd.intake_message_files SET mirrored_file_id = %s, mirrored_at = now()
WHERE message_id = %s AND file_id = %s AND mirrored_at IS NULL
"""


def alt_text(name, mimetype):
    if (mimetype or "").startswith("image/"):
        return f"screenshot the reporter sent, {name}"
    return name


def shows_inline(mimetype):
    return (mimetype or "").lower() in IN_BLOCKS


def upload_file(client, name, body, channel_id=None, thread_ts=None):
    where = {"channel": channel_id, "thread_ts": thread_ts} if channel_id else {}
    response = client.files_upload_v2(content=body, filename=name, title=name, **where)
    return (response.get("files") or [{}])[0].get("id")


def gather(conn, message_id):
    inline, on_their_own = [], []
    for file_id, name, mimetype, sha, _ in conn.execute(TO_SHARE, (message_id,)).fetchall():
        body, stored_type = blobs.body_of(conn, sha)
        if body is None:
            log.warning("nemo: file %s says stored but has no bytes", file_id)
            continue
        kind = mimetype or stored_type
        entry = (file_id, name or f"{sha[:12]}", kind, body)
        (inline if shows_inline(kind) else on_their_own).append(entry)
    return inline, on_their_own


def share(client, conn, message_id, channel_id, thread_ts, author_fields=None, body=None,
          unfurl=True):
    inline, on_their_own = gather(conn, message_id)
    text = (body or "").strip()
    if not inline and not on_their_own and not text:
        return None

    ts = post(
        client, conn, message_id, channel_id, thread_ts, inline, text, on_their_own,
        author_fields or {}, unfurl,
    )

    for file_id, name, _, body in on_their_own:
        try:
            uploaded = upload_file(client, name, body, channel_id, thread_ts)
        except Exception:
            log.exception("nemo: could not carry file %s into the thread", file_id)
            continue
        if uploaded:
            conn.execute(MIRRORED, (uploaded, message_id, file_id))

    return ts


def post(client, conn, message_id, channel_id, thread_ts, inline, text, alongside, author_fields,
         unfurl=True):
    uploaded_files = []
    for file_id, name, kind, body in inline:
        try:
            uploaded = upload_file(client, name, body)
        except Exception:
            log.exception("nemo: could not keep file %s for the thread", file_id)
            continue
        if uploaded:
            uploaded_files.append((file_id, name, kind, uploaded))

    if inline and not uploaded_files:
        raise RuntimeError("slack would not keep any of the pictures, so this is not settled")

    if uploaded_files:
        time.sleep(FILE_INDEX_DELAY)

    if text and not uploaded_files and not alongside:
        return post_text(client, channel_id, thread_ts, text, author_fields, unfurl)

    blocks = []
    if text:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text}})
    for _, name, kind, uploaded in uploaded_files:
        blocks.append({
            "type": "image",
            "slack_file": {"id": uploaded},
            "alt_text": alt_text(name, kind),
        })
    if not blocks and alongside:
        blocks.append(named(alongside))

    if not blocks:
        return None

    sent = client.chat_postMessage(
        channel=channel_id,
        thread_ts=thread_ts,
        text=text or attachment_summary(uploaded_files or alongside),
        blocks=blocks,
        unfurl_links=False,
        unfurl_media=False,
        **author_fields,
    )
    ts = sent["ts"]
    for file_id, _, _, uploaded in uploaded_files:
        conn.execute(MIRRORED, (uploaded, message_id, file_id))
    if uploaded_files:
        log.info("nemo: carried %d file(s) into the internal_log", len(uploaded_files))
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


def named(alongside):
    names = ", ".join(one[1] for one in alongside)
    return {"type": "section", "text": {"type": "mrkdwn", "text": f"Files: {names}"}}


def attachment_summary(files):
    if len(files) == 1:
        return files[0][1]
    return f"{len(files)} attachments"


def fetch(url, token, limit):
    if not blobs.slack_url(url):
        log.warning("nemo: %s is not an https slack url, not asking for it", url)
        return None

    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = response.read(limit + 1)
            return body if len(body) <= limit else None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        log.warning("nemo: could not fetch %s: %s", url, error)
        return None
