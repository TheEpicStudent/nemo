from lyla.categories import Categories

LYLA = [(code, name, True) for code, name in [
    (0, "Misconduct Not Otherwise Specified"), (11, "Spam"), (16, "Slack ban evasion")]]

NEMO = [("nos", "Misconduct not otherwise specified", None),
        ("spam", "Spam, mass pings or invites", None),
        ("ban_evasion", "Slack ban evasion", None),
        ("unwanted_dms", "Unwanted DMs or personal questions", None),
        ("bot_misuse", "Bot or automation misuse", None),
        ("doxxing_lite", "Sharing someone's school", None)]


def test_key_for_static_code_and_by_name():
    categories = Categories(LYLA + [(40, "Sharing someone's school", True)], NEMO)
    assert categories.key_for(11) == "spam"
    assert categories.key_for(40) == "doxxing_lite"
    assert categories.key_for(None) is None
    assert categories.key_for(99) is None


def test_code_for_static_key_and_by_label():
    categories = Categories(LYLA + [(40, "Sharing someone's school", True)], NEMO)
    assert categories.code_for("unwanted_dms") == 17
    assert categories.code_for("doxxing_lite") == 40
    assert categories.code_for(None) is None


def test_wanted_adds_new_codes_renames_spam_and_numbers_custom_categories():
    changes = Categories(LYLA, NEMO).wanted()
    assert ("rename", 11, "Spam, mass pings or invites", True) in changes
    assert ("add", 17, "Unwanted DMs or personal questions", True) in changes
    assert ("add", 21, "Bot or automation misuse", True) in changes
    assert ("add", 22, "Sharing someone's school", True) in changes
    assert not any(code in (0, 16) for _kind, code, _label, _active in changes)


def test_wanted_marks_retired_categories_inactive():
    nemo = [("bot_misuse", "Bot or automation misuse", "2026-10-01")]
    lyla = LYLA + [(21, "Bot or automation misuse", True)]
    assert Categories(lyla, nemo).wanted() == [("rename", 21, "Bot or automation misuse", False)]


def test_wanted_without_differences_is_empty():
    lyla = [(11, "Spam, mass pings or invites", True), (17, "Unwanted DMs or personal questions", True)]
    nemo = [("spam", "Spam, mass pings or invites", None),
            ("unwanted_dms", "Unwanted DMs or personal questions", None)]
    assert Categories(lyla, nemo).wanted() == []
