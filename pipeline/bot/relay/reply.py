ANONYMOUSLY = "sent anonymously"

GOT_IT = "white_check_mark"

NEMO_QUIET_AFTER = "5 minutes"

CATCHING_UP = "Delivery is delayed. Your report is saved, so there is no need to send it again."

HANDOFF_FAILED = "Your report was not sent. Try again in a few minutes."

NEMO_HEARTBEAT = """
SELECT bool_or(beat_at > now() - %s::interval)
FROM raw.worker_heartbeat
WHERE worker LIKE 'bot%%' AND worker LIKE '%%nemo%%'
"""


def nemo_is_behind(conn):
    try:
        row = conn.execute(NEMO_HEARTBEAT, (NEMO_QUIET_AFTER,)).fetchone()
    except Exception:
        return False
    return row is None or not row[0]


SUBMITTED = "Report sent. We usually reply within a couple of hours."


def receipt_text(case_id):
    return SUBMITTED


def receipt(case_id, anonymous, behind=False):
    text = receipt_text(case_id)
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    notes = []
    if anonymous:
        notes.append(ANONYMOUSLY)
    if behind:
        notes.append(CATCHING_UP)
    if notes:
        blocks.append(
            {
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": note} for note in notes],
            }
        )
    return text, blocks


def handoff_failed():
    return HANDOFF_FAILED, [
        {"type": "section", "text": {"type": "mrkdwn", "text": HANDOFF_FAILED}}
    ]
