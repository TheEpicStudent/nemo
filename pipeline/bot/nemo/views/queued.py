from bot.nemo.views import report


def build_blocks(case):
    return [
        part
        for part in [report.title(case), report.quote(case.get("body")), report.buttons(case)]
        if part
    ]


def fallback(case):
    return report.headline(case)


def metadata(case):
    return {
        "event_type": "fd_case_card",
        "event_payload": {"case_id": case["case_id"], "report_id": None},
    }
