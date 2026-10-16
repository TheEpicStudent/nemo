import datetime as dt
import re

LINK = re.compile(r"(<https?://[^\s<>]+?(?:\|[^>]*)?>)")

QUOTE_LIMIT = 2400
CUT = "\n[truncated; the full text is on the case page]"
MEMBER_PART_LIMIT = 3000
SPLIT_POINTS = ("\n\n", "\n", " ")


def escape(text):
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def escape_but_links(text):
    return "".join(
        part if LINK.fullmatch(part) else escape(part)
        for part in LINK.split(text or "")
    )


def quote_text(body, cut=CUT):
    text = (body or "").strip()
    if not text:
        return ""
    if len(text) > QUOTE_LIMIT:
        text = text[:QUOTE_LIMIT].rstrip() + cut
    return text


def split_point(window, limit):
    for separator in SPLIT_POINTS:
        at = window.rfind(separator)
        if at > limit // 2:
            return at
    return limit


def outside_token(window, cut):
    opened = window.rfind("<", 0, cut)
    if opened > 0 and opened > window.rfind(">", 0, cut):
        return opened
    return cut


def split_text(text, limit=MEMBER_PART_LIMIT):
    parts = []
    rest = text
    while len(rest) > limit:
        window = rest[:limit]
        cut = outside_token(window, split_point(window, limit))
        parts.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        parts.append(rest)
    return parts


def member_parts(body):
    text = (body or "").strip()
    return [escape_but_links(part) for part in split_text(text)] if text else []


def short_date(value, today=None):
    if value.year == (today or dt.date.today()).year:
        return value.strftime("%-d %b")
    return value.strftime("%-d %b %Y")


def short_end(value, today=None):
    if not isinstance(value, dt.datetime):
        return short_date(value, today)
    at = value.astimezone(dt.timezone.utc) if value.tzinfo else value
    if (at.hour, at.minute) == (23, 59):
        return short_date(at, today)
    return f"{short_date(at, today)}, {at:%H:%M} UTC"
