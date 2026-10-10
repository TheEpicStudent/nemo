import re

from bot.core import parse, richtext
from bot.core.formatting import quote_text

LINK_TOKEN = re.compile(r"(<https?://[^\s<>]+?(?:\|[^>]*)?>)")

SHOWN_ITEMS = 24


def occurrences(text):
    return [
        {
            "url": found.group(0),
            "channel_id": found.group(1),
            "ts": f"{found.group(2)}.{found.group(3)}",
        }
        for found in parse.ARCHIVE_LINK.finditer(text or "")
    ]


def numbering(text, shares, start):
    links = occurrences(text)
    linked = {(one["channel_id"], one["ts"]) for one in links}
    forwards = [
        share
        for share in shares or []
        if share.get("kind") == "forward"
        and (share.get("source_channel_id"), share.get("source_ts")) not in linked
    ]
    return {"start": start, "links": links, "forwards": forwards}


def size(numbered):
    if not numbered:
        return 0
    return len(numbered["links"]) + len(numbered["forwards"])


def forwarded_lines(numbered):
    first = numbered["start"] + len(numbered["links"])
    return [f"forwarded ({first + seen})" for seen in range(len(numbered["forwards"]))]


def numbered_quote(block, numbered):
    if not numbered or not size(numbered):
        return block

    count = len(numbered["links"])
    runs = []
    seen = 0
    for element in block["elements"][0]["elements"] if block else []:
        runs.append(element)
        if (
            seen < count
            and element.get("type") == "link"
            and parse.ARCHIVE_LINK.search(element.get("url") or "")
        ):
            runs.append({"type": "text", "text": f" ({numbered['start'] + seen})"})
            seen += 1

    for line in forwarded_lines(numbered):
        runs.append({"type": "text", "text": f"\n{line}" if runs else line})

    if not runs:
        return None
    return {"type": "rich_text", "elements": [{"type": "rich_text_quote", "elements": runs}]}


def numbered_text(text, numbered):
    if not numbered or not size(numbered):
        return text

    count = len(numbered["links"])
    parts = []
    seen = 0
    for part in LINK_TOKEN.split(text or ""):
        parts.append(part)
        if seen < count and LINK_TOKEN.fullmatch(part) and parse.ARCHIVE_LINK.search(part):
            parts.append(f" ({numbered['start'] + seen})")
            seen += 1

    return "\n".join(line for line in ["".join(parts), *forwarded_lines(numbered)] if line)


def items(numbered, shares):
    if not numbered:
        return []

    by_source = {
        (share.get("source_channel_id"), share.get("source_ts")): share
        for share in shares or []
    }
    out = []
    number = numbered["start"]
    for one in numbered["links"]:
        out.append({
            "number": number,
            "url": one["url"],
            "channel_id": one["channel_id"],
            "share": by_source.get((one["channel_id"], one["ts"])) or {},
        })
        number += 1
    for share in numbered["forwards"]:
        out.append({
            "number": number,
            "url": share.get("permalink"),
            "channel_id": share.get("source_channel_id"),
            "share": share,
        })
        number += 1
    return out


def channel_ref(share, channel_id=None):
    held = share.get("source_channel_id") or channel_id
    if held:
        return f"<#{held}>"
    named = share.get("source_channel_name")
    return f"#{named}" if named else None


def by_whom(share, channel_id=None):
    who = share.get("source_author_user_id")
    text = f"<@{who}>" if who else "somebody"
    where = channel_ref(share, channel_id)
    return f"{text} in {where}" if where else text


def readable(share):
    return bool(share.get("is_reachable") and (share.get("source_body") or "").strip())


def context(text):
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}


def item_blocks(item):
    share = item["share"]
    number = item["number"]
    head = (
        [richtext.link(item["url"]), {"type": "text", "text": f" ({number})"}]
        if item["url"]
        else [{"type": "text", "text": f"forwarded ({number})"}]
    )

    parts = [{"type": "rich_text_section", "elements": head}]
    if readable(share):
        words = richtext.quote(quote_text(share["source_body"]))
        parts.append(words["elements"][0])

    return [
        {"type": "rich_text", "elements": parts},
        context(by_whom(share, item["channel_id"]) if readable(share) else "can't read it"),
    ]


def reply_blocks(found):
    blocks = []
    for item in found[:SHOWN_ITEMS]:
        blocks += item_blocks(item)
    rest = len(found) - SHOWN_ITEMS
    if rest > 0:
        blocks.append(context(f"{rest} more in Fire Engine"))
    return blocks


def fallback(found):
    return "1 linked message" if len(found) == 1 else f"{len(found)} linked messages"
