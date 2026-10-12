import re

import yaml

from bot.core import richtext
from bot.core.formatting import (
    escape,
    quote_text,
)
from bot.nemo.views import edit, lines, linked
from lib.paths import CATEGORIES_FILE

MENTION = re.compile(r"(<[@#][A-Z0-9][A-Z0-9]*(?:\|[^>]*)?>)")
SLACK_BIT = re.compile(
    r"(<[@#][A-Z0-9][A-Z0-9]*(?:\|[^>]*)?>|<https?://[^\s<>]+?(?:\|[^>]*)?>)"
)

CLAIM = edit.CLAIM
LOG_ACTION = edit.LOG_ACTION
RESOLVE = edit.RESOLVE
REOPEN = edit.REOPEN
OPEN = "case_open"

LABELS = None


def category_label(key):
    global LABELS
    if LABELS is None:
        LABELS = yaml.safe_load(CATEGORIES_FILE.read_text())["categories"]
    if not key:
        return None
    return LABELS.get(key, key.replace("_", " "))


def escape_but_slack(text):
    return "".join(
        part if SLACK_BIT.fullmatch(part) else escape(part)
        for part in SLACK_BIT.split(text or "")
    )


def escape_but_mentions(text):
    return escape_but_slack(text)


def quote(body, blocks=None):
    if blocks:
        made = richtext.quote_blocks(blocks)
        if made:
            return made

    words = quote_text(body)
    return richtext.quote(words) if words else None


def headline(case):
    name = f"Case {case['case_id']}"
    label = category_label(case.get("category_key"))
    return f"{name} · {label}" if label else name


def footer(case):
    name = f"Case {case['case_id']}"
    url = case.get("url")
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": f"<{url}|{name}>" if url else name},
        "accessory": edit.menu(case),
    }


def body(case):
    return linked.plain(
        linked.numbered_quote(quote(case.get("body"), case.get("blocks")), case.get("numbering"))
    )


def header_blocks(case):
    text = lines.header(case["case_id"], case.get("url"))
    return [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]


def build_blocks(case):
    body_block = body(case)
    return [body_block] if body_block else header_blocks(case)


def needs_header(case):
    return body(case) is not None


def fallback(case):
    return headline(case)


def metadata(case):
    return {
        "event_type": "fd_case_card",
        "event_payload": {"case_id": case["case_id"], "report_id": case.get("report_id")},
    }
