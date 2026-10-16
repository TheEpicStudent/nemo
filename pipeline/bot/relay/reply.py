from bot.core.formatting import escape

ANONYMOUS = "Anonymous"

RECEIVED_REACTION = "white_check_mark"

NEMO_HEARTBEAT_MAX_AGE = "5 minutes"

DELIVERY_DELAYED = "Delivery delayed"

SUBMIT_FAILED = "Your report was not sent. Try again in a few minutes."

NEMO_HEARTBEAT = """
SELECT bool_or(beat_at > now() - %s::interval)
FROM raw.worker_heartbeat
WHERE worker LIKE 'bot%%' AND worker LIKE '%%nemo%%'
"""


def nemo_delayed(conn):
    try:
        row = conn.execute(NEMO_HEARTBEAT, (NEMO_HEARTBEAT_MAX_AGE,)).fetchone()
    except Exception:
        return False
    return row is None or not row[0]


SUBMITTED = "Your report was sent to the Fire Department."

THREAD_HINT = "Replies arrive in this thread · Reply here to add details"


def receipt_text(case_id):
    return SUBMITTED


def receipt(case_id, anonymous, delayed=False):
    text = receipt_text(case_id)
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    notes = []
    if anonymous:
        notes.append(ANONYMOUS)
    if delayed:
        notes.append(DELIVERY_DELAYED)
    notes.append(THREAD_HINT)
    blocks.append(
        {
            "type": "context",
            "elements": [{"type": "mrkdwn", "text": note} for note in notes],
        }
    )
    return text, blocks


def submit_failed():
    return SUBMIT_FAILED, [
        {"type": "section", "text": {"type": "mrkdwn", "text": SUBMIT_FAILED}}
    ]


REPORTER_DELETE = "Not removed. Deleted messages stay in your report."

EDITED_PREFIX = "Edited: "

MEBIBYTE = 1024 * 1024


def file_label(name):
    return escape(name or "file")


def file_too_large(name, limit_bytes):
    return f"Not sent: {file_label(name)} (over {limit_bytes // MEBIBYTE} MiB). Send a smaller file or a link."


def file_not_media(name):
    return f"Not sent: {file_label(name)} (only images and videos are accepted)."


def file_external(name):
    return f"Not sent: {file_label(name)} (only files uploaded to Slack are accepted)."


def file_not_downloaded(name):
    return f"Not sent: {file_label(name)} (could not be downloaded). Send it again or send a link."
