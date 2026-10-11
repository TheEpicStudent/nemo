from bot.nemo.views import linked, report


def body(case):
    return linked.plain(
        linked.numbered_quote(report.quote(case.get("body")), case.get("numbering"))
    )


def build_blocks(case):
    said = body(case)
    return [said] if said else report.header_blocks(case)


def needs_header(case):
    return body(case) is not None


def fallback(case):
    return report.headline(case)


def metadata(case):
    return {
        "event_type": "fd_case_card",
        "event_payload": {"case_id": case["case_id"], "report_id": None},
    }
