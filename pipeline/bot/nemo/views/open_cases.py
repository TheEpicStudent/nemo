import datetime as dt
import html
import re

from bot.core import richtext
from bot.nemo.views import lengths, report

SNIPPET_MAX_CHARS = 50
EMPTY_TITLE = "No open cases"
REPORT_LABEL = "Report"
CARD_LABEL = "Case card"
BROADCAST_MENTIONS = {"channel": "@channel", "here": "@here", "everyone": "@everyone"}

SLACK_TOKEN = re.compile(r"<([^<>]+)>")
USER_MENTION = re.compile(r"<@([UW][A-Z0-9]+)(?:\|[^>]*)?>")
CHANNEL_MENTION = re.compile(r"<#(C[A-Z0-9]+)(?:\|[^>]*)?>")


def mention_ids(bodies):
    user_ids, channel_ids = set(), set()
    for body in bodies:
        user_ids.update(USER_MENTION.findall(body or ""))
        channel_ids.update(CHANNEL_MENTION.findall(body or ""))
    return sorted(user_ids), sorted(channel_ids)


def render_slack_token(token, names):
    target, _, label = token.partition("|")
    if target.startswith("@"):
        return label if label.startswith("@") else f"@{label or names.get(target[1:]) or target[1:]}"
    if target.startswith("#"):
        return f"#{label or names.get(target[1:]) or 'channel'}"
    if target.startswith("!"):
        return BROADCAST_MENTIONS.get(target[1:]) or label or ""
    return label or target


def to_plain_text(body, names):
    text = SLACK_TOKEN.sub(lambda match: render_slack_token(match.group(1), names), body or "")
    return " ".join(html.unescape(text).split())


def snippet(body, names, limit=SNIPPET_MAX_CHARS):
    text = to_plain_text(body, names)
    if len(text) <= limit:
        return text
    truncated = text[:limit]
    last_space = truncated.rfind(" ")
    return (truncated[:last_space] if last_space > 0 else truncated).rstrip() + "..."


def age_text(opened_at, now=None):
    seconds = int(((now or dt.datetime.now(dt.UTC)) - opened_at).total_seconds())
    return f"{lengths.span(seconds)} ago"


def case_elements(case, now=None):
    name = f"Case {case['case_id']}"
    case_link = richtext.link(case["url"], name) if case["url"] else richtext.text_element(name)
    case_link["text"] = name
    case_link["style"] = {"bold": True}
    details = "".join(f" · {part}" for part in (report.category_label(case["category_key"]),
                                                 age_text(case["opened_at"], now)) if part)
    elements = [case_link]
    if not case["assignees"]:
        return [*elements, richtext.text_element(details)]
    elements.append(richtext.text_element(f"{details} · Assigned: "))
    for index, user_id in enumerate(case["assignees"]):
        if index:
            elements.append(richtext.text_element(", "))
        elements.append({"type": "user", "user_id": user_id})
    return elements


def entry_elements(entry, names, has_reports):
    label = snippet(entry["body"], names) or (REPORT_LABEL if has_reports else CARD_LABEL)
    if entry["url"]:
        return [{"type": "link", "url": entry["url"], "text": label}]
    return [richtext.text_element(label)]


def bullet_list(sections, indent):
    return {"type": "rich_text_list", "style": "bullet", "indent": indent,
            "elements": [{"type": "rich_text_section", "elements": section} for section in sections]}


def build_message(total, cases, names, now=None, list_url=None):
    if not cases:
        return {"text": EMPTY_TITLE, "blocks": [{"type": "section", "text": {"type": "mrkdwn", "text": EMPTY_TITLE}}]}

    title = f"Open cases ({total})"
    elements = [{"type": "rich_text_section", "elements": [richtext.text_element(title, {"bold": True})]}]
    for case in cases:
        elements.append(bullet_list([case_elements(case, now)], 0))
        if case["entries"]:
            elements.append(bullet_list(
                [entry_elements(entry, names, case["has_reports"]) for entry in case["entries"]], 1))

    blocks = [{"type": "rich_text", "elements": elements}]
    if total > len(cases):
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": f"showing {len(cases)} of {total}"}]})
    if list_url:
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": "Open in Fire Engine"}, "url": list_url},
        ]})
    return {"text": title, "blocks": blocks}
