from bot.nemo import case_actions
from bot.nemo.views import resolve

MOD = "UMOD"
USER_ID = "U1"


class Conn:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return self.rows


def action(**over):
    row = {"target_user_id": USER_ID, "type_key": "warning",
           "reason": "kept at it after being asked to stop"}
    row.update(over)
    return row


def test_resolution_log_actions_returns_unreversed_actions_as_dicts():
    conn = Conn([(USER_ID, "warning", "kept at it")])
    assert case_actions.resolution_log_actions(conn, 412) == [
        {"target_user_id": USER_ID, "type_key": "warning", "reason": "kept at it"},
    ]
    assert conn.executed[0] == (case_actions.RESOLUTION_LOG_ACTIONS, (412,))


def test_log_blocks_no_action_without_case_id_names_disposition_in_byline():
    blocks = resolve.log_blocks("no_action", None, MOD)
    assert blocks == [{
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"Resolved by <@{MOD}> · No action needed"}],
    }]


def test_log_blocks_with_case_id_names_case_in_byline():
    blocks = resolve.log_blocks("no_action", None, MOD, case_id=23)
    assert blocks[0]["elements"][0]["text"] == f"<@{MOD}> resolved case 23 · No action needed"
    blocks = resolve.log_blocks("action_taken", None, MOD, case_id=23)
    assert blocks[0]["elements"][0]["text"] == f"<@{MOD}> resolved case 23"


def test_log_blocks_not_conduct_with_summary_quotes_summary():
    blocks = resolve.log_blocks("not_conduct", "a misunderstanding, nothing more", MOD)
    assert blocks[1] == {"type": "divider"}
    assert blocks[2]["text"]["text"] == "> a misunderstanding, nothing more"


def test_log_blocks_action_taken_omits_disposition_from_byline():
    blocks = resolve.log_blocks("action_taken", None, MOD, [action()])
    assert blocks[0]["elements"][0]["text"] == f"Resolved by <@{MOD}>"


def test_log_blocks_action_taken_lists_each_action_with_reason():
    blocks = resolve.log_blocks(
        "action_taken", None, MOD,
        [action(), action(type_key="channel_ban", target_user_id="U2", reason="repeated spam")],
    )
    assert blocks[1] == {"type": "divider"}
    assert blocks[2]["elements"][0]["text"] == f"*Warning* against <@{USER_ID}>"
    assert blocks[3]["text"]["text"] == "> kept at it after being asked to stop"
    assert blocks[4]["elements"][0]["text"] == "*Channel ban* against <@U2>"
    assert blocks[5]["text"]["text"] == "> repeated spam"


def test_log_blocks_action_taken_with_summary_appends_summary_footer():
    blocks = resolve.log_blocks("action_taken", "both stopped after the ban", MOD, [action()])
    footer = blocks[-1]["elements"][0]["text"]
    assert footer == "*Summary:* both stopped after the ban"
