import datetime as dt
import html
import re

from bot.core import richtext
from bot.nemo.views import lengths, report

SNIPPET = 50
EMPTY = "No open cases"
REPORT = "Report"
CARD = "Case card"
SPECIAL = {"channel": "@channel", "here": "@here", "everyone": "@everyone"}

TOKEN = re.compile(r"<([^<>]+)>")
USER = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
CHANNEL = re.compile(r"<#(C[A-Z0-9]+)(?:\|[^>]*)?>")


def mentioned(bodies):
    users, channels = set(), set()
    for body in bodies:
        users.update(USER.findall(body or ""))
        channels.update(CHANNEL.findall(body or ""))
    return sorted(users), sorted(channels)


def token_text(token, names):
    target, _, label = token.partition("|")
    if target.startswith("@"):
        return label if label.startswith("@") else f"@{label or names.get(target[1:]) or target[1:]}"
    if target.startswith("#"):
        return f"#{label or names.get(target[1:]) or 'channel'}"
    if target.startswith("!"):
        return SPECIAL.get(target[1:]) or label or ""
    return label or target


def plain(body, names):
    text = TOKEN.sub(lambda match: token_text(match.group(1), names), body or "")
    return " ".join(html.unescape(text).split())


def snippet(body, names, limit=SNIPPET):
    text = plain(body, names)
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > 0 else cut).rstrip() + "..."


def age(opened_at, now=None):
    seconds = int(((now or dt.datetime.now(dt.UTC)) - opened_at).total_seconds())
    return f"{lengths.span(seconds)} ago"


def case_line(case, now=None):
    name = f"Case {case['case_id']}"
    head = richtext.link(case["url"], name) if case["url"] else richtext.text_element(name)
    head["text"] = name
    head["style"] = {"bold": True}
    info = "".join(f" · {part}" for part in (report.category_label(case["category_key"]),
                                              age(case["opened_at"], now)) if part)
    elements = [head]
    if not case["assignees"]:
        return [*elements, richtext.text_element(info)]
    elements.append(richtext.text_element(f"{info} · Assigned: "))
    for index, user_id in enumerate(case["assignees"]):
        if index:
            elements.append(richtext.text_element(", "))
        elements.append({"type": "user", "user_id": user_id})
    return elements


def entry_line(entry, names, is_report):
    label = snippet(entry["body"], names) or (REPORT if is_report else CARD)
    if entry["url"]:
        return [{"type": "link", "url": entry["url"], "text": label}]
    return [richtext.text_element(label)]


def bullets(lines, indent):
    return {"type": "rich_text_list", "style": "bullet", "indent": indent,
            "elements": [{"type": "rich_text_section", "elements": line} for line in lines]}


def build(total, cases, names, now=None, list_url=None):
    if not cases:
        return {"text": EMPTY, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": EMPTY}}]}

    title = f"Open cases ({total})"
    elements = [{"type": "rich_text_section", "elements": [richtext.text_element(title, {"bold": True})]}]
    for case in cases:
        elements.append(bullets([case_line(case, now)], 0))
        if case["entries"]:
            elements.append(bullets([entry_line(one, names, case["is_report"]) for one in case["entries"]], 1))

    blocks = [{"type": "rich_text", "elements": elements}]
    if total > len(cases):
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"showing {len(cases)} of {total}"}]})
    if list_url:
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Open in Fire Engine"}, "url": list_url},
        ]})
    return {"text": title, "blocks": blocks}
