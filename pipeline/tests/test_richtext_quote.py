from bot.core import richtext


def section(*elements):
    return {"type": "rich_text", "elements": [
        {"type": "rich_text_section", "elements": list(elements)},
    ]}


def test_quote_blocks_single_section_returns_quote_with_same_elements():
    quote = richtext.quote_blocks([section(
        {"type": "text", "text": "hi "},
        {"type": "user", "user_id": "U1"},
    )])

    assert quote == {
        "type": "rich_text",
        "elements": [{"type": "rich_text_quote", "elements": [
            {"type": "text", "text": "hi "},
            {"type": "user", "user_id": "U1"},
        ]}],
    }


def test_quote_blocks_multiple_sections_merge_into_one_quote():
    quote = richtext.quote_blocks([section({"type": "text", "text": "a"}),
                                   section({"type": "text", "text": "b"})])

    assert quote["elements"][0]["elements"] == [
        {"type": "text", "text": "a"}, {"type": "text", "text": "b"}
    ]


def test_quote_blocks_non_section_element_returns_none():
    quote = richtext.quote_blocks([{"type": "rich_text", "elements": [
        {"type": "rich_text_preformatted", "elements": [{"type": "text", "text": "code"}]},
    ]}])

    assert quote is None


def test_quote_blocks_non_rich_text_block_returns_none():
    quote = richtext.quote_blocks([{"type": "divider"}])

    assert quote is None


def test_quote_blocks_empty_input_returns_none():
    assert richtext.quote_blocks(None) is None
    assert richtext.quote_blocks([]) is None
    assert richtext.quote_blocks([section()]) is None
