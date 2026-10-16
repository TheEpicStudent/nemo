from bot.nemo import case_actions
from bot.nemo.views import people

DROPPED_COLUMN = "detail"


class Conn:
    def __init__(self, rows=(), one=None):
        self.rows = rows
        self.one = one
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.one

    def args_for(self, mark):
        return [args for sql, args in self.executed if mark in sql]


def test_participants_returns_user_id_and_role_dicts():
    conn = Conn(rows=[("U1", "subject"), ("U2", "reporter")])

    assert case_actions.participants(conn, 6) == [
        {"user_id": "U1", "role": "subject"},
        {"user_id": "U2", "role": "reporter"},
    ]


def test_remove_participant_audits_removed_user_and_role():
    conn = Conn(one=("U1",))

    assert case_actions.remove_participant(conn, 6, "U1", "subject", "UFD") is True
    before = conn.args_for("INSERT INTO fd.audit")[0][5].obj
    assert before == {"user_id": "U1", "role": "subject"}


def test_remove_participant_missing_member_returns_false_without_audit():
    conn = Conn(one=None)

    assert case_actions.remove_participant(conn, 6, "U1", "subject", "UFD") is False
    assert conn.args_for("INSERT INTO fd.audit") == []


def test_participant_queries_exclude_column_dropped_in_0112():
    statements = [case_actions.PARTICIPANTS, case_actions.ADD_PARTICIPANT, case_actions.REMOVE_PARTICIPANT]
    assert [one for one in statements if DROPPED_COLUMN in one] == []


def test_submitted_values_returns_subjects_and_assignees():
    submitted_values = people.submitted_values({"values": {people.WHO: {people.WHO: {"selected_users": ["U1"]}}}})
    assert submitted_values == {"subjects": ["U1"], "assignees": []}


def test_build_view_renders_subject_and_assignee_sections():
    view = people.build_view(9, [{"user_id": "UBOB", "role": "subject"}], ["UME"])
    texts = [block["text"]["text"] for block in view["blocks"] if block["type"] == "section"]
    assert texts == ["<@UBOB> · Subject", "<@UME> · Assigned"]
    assert {block.get("block_id") for block in view["blocks"]} >= {people.WHO, people.ASSIGN}
    remove_values = [block["accessory"]["value"] for block in view["blocks"] if "accessory" in block]
    assert remove_values == ["UBOB:subject:9", "UME:assignee:9"]


def test_build_view_without_can_people_omits_people_selector():
    view = people.build_view(9, [{"user_id": "UBOB", "role": "subject"}], ["UME"],
                              can_people=False, can_assign=True)
    assert people.WHO not in {block.get("block_id") for block in view["blocks"]}
    assert [block["accessory"]["value"] for block in view["blocks"] if "accessory" in block] \
        == ["UME:assignee:9"]


def test_validation_errors_empty_selection_reports_first_visible_field():
    assert people.validation_errors({"subjects": [], "assignees": []}, {people.WHO, people.ASSIGN}) \
        == {people.WHO: "Select a member"}
    assert people.validation_errors({"subjects": [], "assignees": []}, {people.ASSIGN}) \
        == {people.ASSIGN: "Select a member"}
    assert people.validation_errors({"subjects": [], "assignees": ["UME"]}, {people.WHO}) is None
