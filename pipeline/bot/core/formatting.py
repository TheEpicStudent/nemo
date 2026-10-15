import datetime as dt
import re

LINK = re.compile(r"(<https?://[^\s<>]+?(?:\|[^>]*)?>)")

QUOTE_LIMIT = 2400
CUT = "\n[truncated; the full text is on the case page]"
REPORTER_CUT = "\n[truncated]"


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


def to_member(body):
    return escape_but_links(quote_text(body, REPORTER_CUT))


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
