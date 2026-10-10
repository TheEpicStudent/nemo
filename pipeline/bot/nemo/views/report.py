import re

import yaml

from bot.core import richtext
from bot.core.formatting import (
    escape,
    quote_text,
)
from bot.nemo.views import edit
from lib.paths import CATEGORIES_FILE

MENTION = re.compile(r"(<[@#][A-Z0-9][A-Z0-9]*(?:\|[^>]*)?>)")
SLACK_BIT = re.compile(
    r"(<[@#][A-Z0-9][A-Z0-9]*(?:\|[^>]*)?>|<https?://[^\s<>]+?(?:\|[^>]*)?>)"
)

SECTION_LIMIT = 3000
CONTEXT_ELEMENTS = 10
HEADER_LIMIT = 150

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


def category_text(case):
    label = category_label(case.get("category_key"))
    channel = where(case)
    if label and channel:
        return f"{label} in {channel}"
    if label:
        return label
    if channel:
        return f"a report about {channel}"
    return None


def headline(case):
    name = f"Case {case['case_id']}"
    what = category_text(case)
    return f"{name} · {what}" if what else name


def title(case):
    return {
        "type": "header",
        "text": {"type": "plain_text", "text": headline(case)[:HEADER_LIMIT]},
    }


def subjects_line(case):
    subjects = case.get("subjects") or []
    if not subjects:
        return None
    return "about " + ", ".join(f"<@{user_id}>" for user_id in subjects)


def link(case):
    url = case.get("url")
    return f"<{url}|open in fire engine>" if url else None


def reporter(case):
    if case.get("is_anonymous", True) or not case.get("reporter_user_id"):
        return "Anonymous"
    return f"<@{case['reporter_user_id']}>"


def reported(case):
    if case.get("is_anonymous", True) or not case.get("reporter_user_id"):
        return "reported anonymously"
    return f"{reporter(case)} reported it"


def subject_summary_text(case):
    parts = [reported(case), subjects_line(case)]
    return context([" · ".join(part for part in parts if part)])


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


SHOWN_SHARES = 3


def evidence_blocks(shares):
    return [
        share
        for share in shares
        if share.get("is_reachable") and (share.get("source_body") or "").strip()
    ][:SHOWN_SHARES]


def channel_ref(share):
    held = share.get("source_channel_id")
    if held:
        return f"<#{held}>"
    named = share.get("source_channel_name")
    return f"#{named}" if named else None


def whose(share):
    who = share.get("source_author_user_id")
    where = channel_ref(share)
    text = f"<@{who}>" if who else "somebody"
    if where:
        text += f" in {where}"
    permalink = share.get("permalink")
    return f"{text} · <{permalink}|open it>" if permalink else text


def report_body_text(case):
    built = []
    for share in evidence_blocks(case.get("shares") or []):
        built.append(context([whose(share)]))
        words = quote(share["source_body"])
        if words:
            built.append(words)
    return built


def build_blocks(case):
    built = [part for part in [
        title(case), subject_summary_text(case), quote(case.get("body"), case.get("blocks")),
    ] if part]
    built += report_body_text(case)

    acting = buttons(case)
    if acting:
        built.append(acting)

    return built


def fallback(case):
    return f"Case {case['case_id']}: {headline(case).lower()}"


def metadata(case):
    return {
        "event_type": "fd_case_card",
        "event_payload": {"case_id": case["case_id"], "report_id": case.get("report_id")},
    }
