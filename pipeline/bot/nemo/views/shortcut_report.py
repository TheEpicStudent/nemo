from bot.core import richtext
from bot.core.formatting import quote_text

SHORTCUT = "shortcut"
VIEW_MESSAGE = "View message"
BOT = "Bot"
SEPARATOR = " · "


def is_shortcut(case):
    return case.get("entry_point") == SHORTCUT


def source_share(case):
    for share in case.get("shares") or []:
        if share.get("kind") == "forward":
            return share
    return {}


def quote(case):
    value = richtext.quote_blocks(case.get("blocks"))
    if value:
        return value
    words = quote_text(case.get("body"))
    return richtext.quote(words) if words else None


def attribution(share):
    channel_id = share.get("source_channel_id")
    where = f"<#{channel_id}>" if channel_id else None
    author_id = share.get("source_author_user_id")
    kind = (share.get("raw") or {}).get("author_kind")
    who = f"<@{author_id}>" if author_id else (None if kind == "withheld" else BOT)
    if who and where:
        return f"{who} in {where}"
    return who or where or ""


def source_line(share):
    parts = [attribution(share)]
    if share.get("permalink"):
        parts.append(f"<{share['permalink']}|{VIEW_MESSAGE}>")
    return SEPARATOR.join(part for part in parts if part)


def context_block(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def blocks(case):
    built = []
    quoted = quote(case)
    if quoted:
        built.append(quoted)
    line = source_line(source_share(case))
    if line:
        built.append(context_block(line))
    return built
