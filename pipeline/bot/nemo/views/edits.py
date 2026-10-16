from bot.core import richtext
from bot.core.formatting import quote_text

EDITED = "Reporter edited a message"
NO_TEXT = "No text"
MODERATOR_DELETE = "Deletion not forwarded. The reporter still has this reply."


def label(text):
    return {"type": "rich_text_section", "elements": [richtext.text_element(text, {"bold": True})]}


def quote(text):
    body = quote_text(text) or NO_TEXT
    return {"type": "rich_text_quote", "elements": richtext.elements(body)}


def edit_notice(url, before, after):
    head = f"{EDITED} · <{url}|message>" if url else EDITED
    return {
        "text": EDITED,
        "blocks": [
            {"type": "context", "elements": [{"type": "mrkdwn", "text": head}]},
            {"type": "rich_text", "elements": [label("From"), quote(before), label("To"), quote(after)]},
        ],
    }
