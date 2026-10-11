from bot.core import parse


def picture(file_id):
    return {"id": file_id, "name": "image.png", "mimetype": "image/png", "mode": "hosted",
            "url_private": f"https://files.slack.com/{file_id}/image.png"}


def test_a_forwarded_picture_is_kept_like_one_sent_directly():
    event = {"files": [picture("F1")], "attachments": [
        {"is_share": True, "files": [picture("F2")]},
    ]}

    found = parse.files(event)

    assert [one["slack_file_id"] for one in found] == ["F1", "F2"]
    assert all(one["fetch_state"] == "pending" for one in found)


def test_a_link_preview_brings_no_files_along():
    event = {"attachments": [{"is_msg_unfurl": True, "files": [picture("F3")]}]}

    assert parse.files(event) == []


def test_a_file_both_sent_and_forwarded_is_kept_once():
    event = {"files": [picture("F1")], "attachments": [{"is_share": True, "files": [picture("F1")]}]}

    assert len(parse.files(event)) == 1
