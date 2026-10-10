import re

import yaml

from bot.core import richtext
from bot.core.formatting import (
    escape,
    quote_text,
)
from bot.nemo.views import edit, linked
from lib.paths import CATEGORIES_FILE

MENTION = re.compile(r"(<[@#][A-Z0-9][A-Z0-9]*(?:\|[^>]*)?>)")
SLACK_BIT = re.compile(
    r"(<[@#][A-Z0-9][A-Z0-9]*(?:\|[^>]*)?>|<https?://[^\s<>]+?(?:\|[^>]*)?>)"
)

SECTION_LIMIT = 3000
CONTEXT_ELEMENTS = 10

CLAIM = "case_claim"
LOG_ACTION = "case_log_action"
RESOLVE = "case_resolve_open"
REOPEN = "case_reopen"
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


def section(text):
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:SECTION_LIMIT]}}


def context(parts):
    kept = [part for part in parts if part][:CONTEXT_ELEMENTS]
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": part} for part in kept]}


def where(case):
    for share in case.get("shares") or []:
        named = share.get("source_channel_name")
        if named:
            return f"#{named}"
    return None


def place(case):
    for share in case.get("shares") or []:
        found = linked.channel_ref(share)
        if found:
            return found
    return None


def category_text(case, channel=None):
    label = category_label(case.get("category_key"))
    if label and channel:
        return f"{label} in {channel}"
    if label:
        return label
    if channel:
        return f"in {channel}"
    return None


def headline(case):
    name = f"Case {case['case_id']}"
    what = category_text(case, where(case))
    return f"{name} · {what}" if what else name


def title(case):
    parts = [f"Case {case['case_id']}", category_text(case, place(case)), subjects_line(case)]
    return section("*" + escape_but_slack(" · ".join(part for part in parts if part)) + "*")


def subjects_line(case):
    subjects = case.get("subjects") or []
    if not subjects:
        return None
    return "about " + ", ".join(f"<@{user_id}>" for user_id in subjects)


def button(action_id, label, case_id, style=None):
    made = {
        "type": "button",
        "action_id": action_id,
        "text": {"type": "plain_text", "text": label},
        "value": str(case_id),
    }
    if style:
        made["style"] = style
    return made


REOPEN_CONFIRM = {
    "title": {"type": "plain_text", "text": "Reopen it?"},
    "text": {
        "type": "mrkdwn",
        "text": "This drops the resolution and takes everybody off it. "
        "The case comes back unclaimed.",
    },
    "confirm": {"type": "plain_text", "text": "Reopen"},
    "deny": {"type": "plain_text", "text": "Leave it closed"},
}


def open_button(case):
    url = case.get("url")
    if not url:
        return None
    return {
        "type": "button",
        "action_id": OPEN,
        "text": {"type": "plain_text", "text": "Open in Fire Engine"},
        "url": url,
    }


def buttons(case):
    case_id = case["case_id"]
    opening = open_button(case)

    if case.get("resolved_at"):
        back = button(REOPEN, "Reopen", case_id)
        back["confirm"] = REOPEN_CONFIRM
        elements = [back, opening]
    else:
        held = case.get("assignees") or []
        elements = [] if held else [button(CLAIM, "Claim it", case_id, "primary")]
        elements += [
            button(LOG_ACTION, "Log an action", case_id),
            button(RESOLVE, "Resolve", case_id, "danger"),
            opening,
            edit.menu(case),
        ]

    return {
        "type": "actions",
        "block_id": f"case_{case_id}",
        "elements": [one for one in elements if one],
    }


def body(case):
    return linked.numbered_quote(quote(case.get("body"), case.get("blocks")), case.get("numbering"))


def build_blocks(case):
    return [part for part in [title(case), body(case), buttons(case)] if part]


def fallback(case):
    return f"Case {case['case_id']}: {headline(case).lower()}"


def metadata(case):
    return {
        "event_type": "fd_case_card",
        "event_payload": {"case_id": case["case_id"], "report_id": case.get("report_id")},
    }
