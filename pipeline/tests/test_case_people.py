from bot.nemo import case_actions
from bot.nemo.views import people

DROPPED = "detail"


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


def test_the_people_on_a_case_are_a_user_and_a_role():
    conn = Conn(rows=[("U1", "subject"), ("U2", "reporter")])

    assert case_actions.participants(conn, 6) == [
        {"user_id": "U1", "role": "subject"},
        {"user_id": "U2", "role": "reporter"},
    ]


def test_taking_somebody_off_writes_down_who_and_what_they_were():
    conn = Conn(one=("U1",))

    assert case_actions.remove_participant(conn, 6, "U1", "subject", "UFD") is True
    before = conn.args_for("INSERT INTO fd.audit")[0][5].obj
    assert before == {"user_id": "U1", "role": "subject"}


def test_taking_off_somebody_who_is_not_there_changes_nothing():
    conn = Conn(one=None)

    assert case_actions.remove_participant(conn, 6, "U1", "subject", "UFD") is False
    assert conn.args_for("INSERT INTO fd.audit") == []


def test_no_query_asks_for_the_column_0112_dropped():
    statements = [case_actions.PARTICIPANTS, case_actions.ADD_PARTICIPANT, case_actions.REMOVE_PARTICIPANT]
    assert [one for one in statements if DROPPED in one] == []


def test_the_people_modal_sends_only_what_the_table_holds():
    submitted_values = people.submitted_values({"values": {people.WHO: {people.WHO: {"selected_users": ["U1"]}}}})
    assert submitted_values == {"subjects": ["U1"], "assignees": []}


def test_subjects_and_assignees_share_one_modal():
    built = people.build_view(9, [{"user_id": "UBOB", "role": "subject"}], ["UME"])
    texts = [block["text"]["text"] for block in built["blocks"] if block["type"] == "section"]
    assert texts == ["<@UBOB> · Subject", "<@UME> · Assigned"]
    assert {block.get("block_id") for block in built["blocks"]} >= {people.WHO, people.ASSIGN}
    remove_values = [block["accessory"]["value"] for block in built["blocks"] if "accessory" in block]
    assert remove_values == ["UBOB:subject:9", "UME:assignee:9"]


def test_the_modal_offers_only_what_you_may_change():
    built = people.build_view(9, [{"user_id": "UBOB", "role": "subject"}], ["UME"],
                              can_people=False, can_assign=True)
    assert people.WHO not in {block.get("block_id") for block in built["blocks"]}
    assert [block["accessory"]["value"] for block in built["blocks"] if "accessory" in block] \
        == ["UME:assignee:9"]


def test_adding_nobody_is_held_back_on_the_first_field_shown():
    assert people.validation_errors({"subjects": [], "assignees": []}, {people.WHO, people.ASSIGN}) \
        == {people.WHO: "Pick somebody first."}
    assert people.validation_errors({"subjects": [], "assignees": []}, {people.ASSIGN}) \
        == {people.ASSIGN: "Pick somebody first."}
    assert people.validation_errors({"subjects": [], "assignees": ["UME"]}, {people.WHO}) is None
