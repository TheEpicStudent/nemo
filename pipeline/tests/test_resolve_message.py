from bot.nemo.views import resolve


def rich_text_state(elements):
    return {"values": {
        resolve.RESOLUTION: {resolve.RESOLUTION: {"selected_option": {"value": "action_taken"}}},
        resolve.NOTIFY: {resolve.NOTIFY: {"selected_options": [{"value": resolve.NOTIFY_REPORTER}]}},
        resolve.MESSAGE: {resolve.MESSAGE: {"rich_text_value": {"type": "rich_text", "elements": [
            {"type": "rich_text_section", "elements": elements}]}}},
    }}


def test_build_view_message_field_is_rich_text_with_default_value():
    view = resolve.build_view(12, open_reports=1)
    field = next(block for block in view["blocks"] if block.get("block_id") == resolve.MESSAGE)

    assert field["element"]["type"] == "rich_text_input"
    assert field["element"]["initial_value"]["elements"][0]["elements"][0]["text"] == resolve.default_message()


def test_submitted_values_message_keeps_user_mention_and_validates():
    values = resolve.submitted_values(rich_text_state([
        {"type": "text", "text": "thanks, "}, {"type": "user", "user_id": "U123ABC"}, {"type": "text", "text": " helped"},
    ]))

    assert values["message"] == "thanks, <@U123ABC> helped"
    assert resolve.validation_errors(values) is None


def test_submitted_values_empty_message_uses_default():
    values = resolve.submitted_values(rich_text_state([]))

    assert values["message"] == resolve.default_message()
