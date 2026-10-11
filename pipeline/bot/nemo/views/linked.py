import re

from bot.core import parse, richtext
from bot.core.formatting import quote_text

LINK_TOKEN = re.compile(r"(<https?://[^\s<>]+?(?:\|[^>]*)?>)")

MESSAGE_RUNS = ("link", "message_mention")

BLOCK_LIMIT = 50


def target(token):
    return token[1:-1].split("|", 1)[0]


def message_link(token):
    return parse.ARCHIVE_LINK.match(target(token))


def occurrence(url, matched):
    return {
        "url": url,
        "channel_id": matched.group(1),
        "ts": f"{matched.group(2)}.{matched.group(3)}",
        "thread_ts": parse.thread_of(matched.group(4)),
    }


def occurrences(text):
    found = []
    for part in LINK_TOKEN.split(text or ""):
        if LINK_TOKEN.fullmatch(part):
            matched = message_link(part)
            if matched:
                found.append(occurrence(target(part), matched))
            continue
        for matched in parse.ARCHIVE_LINK.finditer(part):
            found.append(occurrence(matched.group(0), matched))
    return found


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
            and element.get("type") in MESSAGE_RUNS
            and parse.ARCHIVE_LINK.match(element.get("url") or "")
        ):
            runs.append({"type": "text", "text": f" ({numbered['start'] + seen})"})
            seen += 1

    for line in forwarded_lines(numbered):
        runs.append({"type": "text", "text": f"\n{line}" if runs else line})

    if not runs:
        return None
    return {"type": "rich_text", "elements": [{"type": block_kind(block), "elements": runs}]}


def block_kind(block):
    return block["elements"][0]["type"] if block else "rich_text_section"


def plain(block):
    if not block:
        return block
    runs = block["elements"][0]["elements"]
    return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": runs}]}


def numbered_text(text, numbered):
    if not numbered or not size(numbered):
        return text

    count = len(numbered["links"])
    parts = []
    seen = 0
    for part in LINK_TOKEN.split(text or ""):
        parts.append(part)
        if seen < count and LINK_TOKEN.fullmatch(part) and message_link(part):
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
        full = by_source.get((share.get("source_channel_id"), share.get("source_ts"))) or share
        out.append({
            "number": number,
            "url": full.get("permalink"),
            "channel_id": full.get("source_channel_id"),
            "share": full,
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


def file_ids(share):
    raw = share.get("raw") if isinstance(share.get("raw"), dict) else {}
    return [one["id"] for one in raw.get("files") or [] if isinstance(one, dict) and one.get("id")]


def carried(share, held):
    found = [held[one] for one in file_ids(share) if one in (held or {})]
    pictures = [
        {"type": "image", "slack_file": {"id": one["id"]}, "alt_text": one["name"]}
        for one in found if one["image"]
    ]
    named = [one["name"] for one in found if not one["image"]]
    return pictures + ([context(":paperclip: " + ", ".join(named))] if named else [])


def item_blocks(item, held=None):
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
        *carried(share, held),
        context(by_whom(share, item["channel_id"]) if readable(share) else "Message not accessible"),
    ]


def reply_blocks(found, held=None):
    blocks = []
    for at, item in enumerate(found):
        made = item_blocks(item, held)
        if len(blocks) + len(made) > BLOCK_LIMIT - 1:
            blocks.append(context(f"{len(found) - at} more in Fire Engine"))
            return blocks
        blocks += made
    return blocks


def fallback(found):
    return "1 linked message" if len(found) == 1 else f"{len(found)} linked messages"
