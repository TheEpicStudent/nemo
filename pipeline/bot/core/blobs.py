import hashlib
import os
from urllib.parse import urlparse

DEFAULT_CAP = 25 * 1024 * 1024
HTML = ("text/html", "application/xhtml+xml")
SLACK_HOSTS = (".slack.com", ".slack-edge.com", ".slack-files.com")

NOT_MEDIA = "not an image or video"
NOT_SLACK_URL = "the file url is not an https slack url"
HTML_BODY = "Slack returned HTML instead of file content"

MEDIA_TYPES = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/heic", "image/heif",
    "video/mp4", "video/quicktime", "video/webm",
})
HEIF_BRANDS = frozenset({b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"})
QUICKTIME_BRANDS = frozenset({b"qt  "})
MP4_BRANDS = frozenset({
    b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"M4VP",
    b"dash", b"3gp4", b"3gp5", b"3gp6", b"3g2a", b"f4v ", b"MSNV",
})


def is_media_type(mimetype):
    return (mimetype or "").split(";")[0].strip().lower() in MEDIA_TYPES


def media_type(body):
    head = bytes(body[:32]) if body else b""
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"\x1a\x45\xdf\xa3"):
        return "video/webm"
    if head[4:8] == b"ftyp":
        brand = head[8:12]
        if brand in HEIF_BRANDS:
            return "image/heic"
        if brand in QUICKTIME_BRANDS:
            return "video/quicktime"
        if brand in MP4_BRANDS:
            return "video/mp4"
    return None


def slack_url(url):
    try:
        parsed = urlparse(url or "")
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (
        host == "slack.com" or host.endswith(SLACK_HOSTS)
    )

IN_SUBMITTED_CONVERSATION = """
EXISTS (
    SELECT 1
    FROM fd.intake_message_files mf
    JOIN fd.intake_messages m ON m.id = mf.message_id
    JOIN fd.intake_conversations c ON c.id = m.conversation_id
    WHERE mf.file_id = f.id AND c.handed_off_at IS NOT NULL
)
"""

PENDING = f"""
SELECT f.id, f.slack_file_id, f.url_private, f.size_bytes, f.mimetype
FROM fd.intake_files f
WHERE f.fetch_state = 'pending' AND f.url_private IS NOT NULL
  AND {IN_SUBMITTED_CONVERSATION}
ORDER BY f.first_seen_at, f.id
LIMIT %s
"""


def cap():
    raw = os.environ.get("INTAKE_FILE_MAX_BYTES")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_CAP
    return value if value > 0 else DEFAULT_CAP


def verdict(status, content_type, size, limit=None):
    limit = cap() if limit is None else limit
    if status in (401, 403):
        return "refused", f"Slack returned {status}: the token cannot read this file"
    if status == 404 or status == 410:
        return "gone", None
    if status != 200:
        return "failed", f"Slack returned {status}"
    if (content_type or "").split(";")[0].strip().lower() in HTML:
        return "refused", HTML_BODY
    if size is not None and size > limit:
        return "too_large", f"{size} bytes is over the {limit} byte limit"
    if not size:
        return "failed", "Slack returned an empty body"
    return "stored", None


def exceeds_limit(size, limit=None):
    limit = cap() if limit is None else limit
    return bool(size) and size > limit


def waiting(conn, limit=20):
    return conn.execute(PENDING, (limit,)).fetchall()


def store_blob(conn, file_id, body, mimetype):
    sha = hashlib.sha256(body).hexdigest()
    conn.execute(
        "INSERT INTO fd.intake_file_blobs (sha256, body, size_bytes, mimetype) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (sha256) DO NOTHING",
        (sha, body, len(body), mimetype),
    )
    conn.execute(
        "UPDATE fd.intake_files SET fetch_state = 'stored', sha256 = %s, stored_key = %s, "
        "stored_bytes = %s, fetched_at = now(), fetch_error = NULL, "
        "fetch_attempts = fetch_attempts + 1 WHERE id = %s",
        (sha, sha, len(body), file_id),
    )
    return sha


def insert_blob(conn, body, mimetype):
    sha = hashlib.sha256(body).hexdigest()
    conn.execute(
        "INSERT INTO fd.intake_file_blobs (sha256, body, size_bytes, mimetype) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (sha256) DO NOTHING",
        (sha, body, len(body), mimetype),
    )
    return sha


def mark_failed(conn, file_id, state, error):
    conn.execute(
        "UPDATE fd.intake_files SET fetch_state = %s, fetch_error = %s, "
        "fetch_attempts = fetch_attempts + 1, fetched_at = now() WHERE id = %s",
        (state, error, file_id),
    )


ORPHAN_BLOBS = """
DELETE FROM fd.intake_file_blobs b
WHERE NOT EXISTS (SELECT 1 FROM fd.intake_files f WHERE f.stored_key = b.sha256)
  AND NOT EXISTS (
      SELECT 1 FROM fd.intake_outbox o
      WHERE o.files @> jsonb_build_array(jsonb_build_object('sha256', b.sha256))
  )
"""


def delete_orphan_blobs(conn):
    return conn.execute(ORPHAN_BLOBS).rowcount


def purge(conn, file_id, purged_by):
    conn.execute(
        "UPDATE fd.intake_files SET fetch_state = 'purged', stored_key = NULL, "
        "stored_bytes = NULL, purged_at = now(), purged_by = %s "
        "WHERE id = %s AND purged_at IS NULL",
        (purged_by, file_id),
    )
    return delete_orphan_blobs(conn)


PURGE_CONVERSATION_FILES = f"""
UPDATE fd.intake_files f
SET fetch_state = 'purged', stored_key = NULL, stored_bytes = NULL,
    purged_at = now(), purged_by = %(by)s
WHERE f.purged_at IS NULL
  AND EXISTS (
      SELECT 1
      FROM fd.intake_message_files mf
      JOIN fd.intake_messages m ON m.id = mf.message_id
      WHERE mf.file_id = f.id AND m.conversation_id = %(conversation)s
  )
  AND NOT {IN_SUBMITTED_CONVERSATION}
"""


def purge_conversation(conn, conversation_id, purged_by):
    purged = conn.execute(
        PURGE_CONVERSATION_FILES, {"by": purged_by, "conversation": conversation_id}
    ).rowcount
    return purged, delete_orphan_blobs(conn)


def body_of(conn, sha):
    row = conn.execute(
        "SELECT body, mimetype FROM fd.intake_file_blobs WHERE sha256 = %s", (sha,)
    ).fetchone()
    return (bytes(row[0]), row[1]) if row else (None, None)
