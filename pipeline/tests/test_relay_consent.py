from bot.relay import consent


def checkbox(blocks):
    return next(block for block in blocks if block.get("block_id") == consent.BLOCK)["elements"][0]


def test_identity_option_keeps_label_and_describes_both_choices():
    option = consent.IDENTITY_OPTION

    assert option["text"]["text"] == "Send anonymously"
    assert option["description"]["text"] == (
        "FD will not see who filed this report. Leave unchecked to include your username.")
    assert option["value"] == consent.ANONYMOUSLY


def test_checkbox_offers_the_described_option():
    assert checkbox(consent.build_blocks())["options"] == [consent.IDENTITY_OPTION]
