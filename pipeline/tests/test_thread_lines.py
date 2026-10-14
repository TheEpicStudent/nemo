from bot.nemo.views import lines


def test_claim_and_assign_read_plainly():
    assert lines.claimed("UME", 39) == "<@UME> claimed case 39"
    assert lines.assigned("UME", 39, ["UA"]) == ["<@UME> assigned case 39 to <@UA>"]
    assert lines.assigned("UME", 39, ["UA", "UB"]) == ["<@UME> assigned case 39 to <@UA> and <@UB>"]
    assert lines.assigned("UME", 39, ["UME"]) == ["<@UME> claimed case 39"]


def test_unassigning_yourself_says_themselves():
    assert lines.unassigned("UME", 39, ["UA"]) == "<@UME> unassigned <@UA> from case 39"
    assert lines.unassigned("UME", 39, ["UME"]) == "<@UME> unassigned themselves from case 39"


def test_a_merge_links_each_case():
    def url(case_id):
        return f"https://fire.example/fd/cases/{case_id}"

    assert lines.merged("UME", [25], 39, url) == (
        "<@UME> merged case <https://fire.example/fd/cases/25|25> into case "
        "<https://fire.example/fd/cases/39|39>"
    )
    assert lines.merged("UME", [25, 31], 39) == "<@UME> merged cases 25 and 31 into case 39"


def test_the_rest_of_the_wording():
    assert lines.header(39, "https://x/39") == "<https://x/39|Case 39>"
    assert lines.resolved("UME", 39, "Not a conduct matter") == (
        "<@UME> resolved case 39 · Not a conduct matter")
    assert lines.reopened("UME", 39) == "<@UME> reopened case 39"
    assert lines.reopened_by_reporter(39, "No action needed") == (
        "Case 39 reopened after the reporter replied (was No action needed)")
    assert lines.note_added("UME", "spoke to them") == "<@UME> added a note: spoke to them"
    assert lines.already_claimed(39) == "You are already assigned to case 39"
    assert lines.already_assigned(39, ["UA"]) == "<@UA> is already assigned to case 39"
    assert lines.not_assigned(39, ["UA", "UB"]) == "<@UA> and <@UB> are not assigned to case 39"
