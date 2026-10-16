import html
import re

LEADING_USER_ID = re.compile(r"\A([UW](?=[A-Z0-9]*\d)[A-Z0-9]{6,})(?=\s|\Z)")

PIECE = re.compile(
    r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>"
    r"|<#(C[A-Z0-9]+)(?:\|[^>]*)?>"
    r"|<(https?://[^|>\s]+)(?:\|([^>]*))?>"
    r"|(?<![<|])(https?://[^\s<>]+)"
)


def leading_user_id(text):
    body = (text or "").lstrip()
    match = LEADING_USER_ID.match(body)
    if not match:
        return None, text
    return match.group(1), body[match.end():].strip()


def link(url, label=None):
    href = html.unescape(url)
    element = {"type": "link", "url": href}
    text = html.unescape(label or "")
    if text and text != href:
        element["text"] = text
    return element


def elements(text, style=None):
    body = text or ""
    out = []
    position = 0

    for match in PIECE.finditer(body):
        preceding_text = body[position : match.start()]
        if preceding_text:
            out.append(text_element(preceding_text, style))

        user_id, channel_id, url, label, bare = match.groups()
        if user_id:
            out.append({"type": "user", "user_id": user_id})
        elif channel_id:
            out.append({"type": "channel", "channel_id": channel_id})
        elif url:
            out.append(link(url, label))
        else:
            out.append(link(bare))
        position = match.end()

    tail = body[position:]
    if tail or not out:
        out.append(text_element(tail, style))
    return out


def text_element(text, style=None):
    element = {"type": "text", "text": text}
    if style:
        element["style"] = style
    return element


def flatten(value):
    if not value:
        return ""

    parts = []
    for block in value.get("elements") or []:
        for part in block.get("elements") or []:
            kind = part.get("type")
            if kind == "user":
                parts.append(f"<@{part['user_id']}>")
            elif kind == "channel":
                parts.append(f"<#{part['channel_id']}>")
            elif kind == "link":
                parts.append(part.get("url") or "")
            elif kind == "emoji":
                parts.append(f":{part.get('name')}:")
            else:
                parts.append(part.get("text") or "")
        parts.append("\n")

    return "".join(parts).strip()


def quote(text, style=None):
    return {
        "type": "rich_text",
        "elements": [{"type": "rich_text_quote", "elements": elements(text, style)}],
    }


def quote_blocks(blocks):
    runs = []
    for block in blocks or []:
        if block.get("type") != "rich_text":
            return None
        for part in block.get("elements") or []:
            if part.get("type") != "rich_text_section":
                return None
            runs.extend(part.get("elements") or [])

    if not runs:
        return None
    return {"type": "rich_text", "elements": [{"type": "rich_text_quote", "elements": runs}]}
