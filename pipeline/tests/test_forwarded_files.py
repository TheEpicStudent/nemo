from bot.core import parse


def image_file(file_id):
    return {"id": file_id, "name": "image.png", "mimetype": "image/png", "mode": "hosted",
            "url_private": f"https://files.slack.com/{file_id}/image.png"}


def test_a_forwarded_picture_is_kept_like_one_sent_directly():
    event = {"files": [image_file("F1")], "attachments": [
        {"is_share": True, "files": [image_file("F2")]},
    ]}

    files = parse.files(event)

    assert [one["slack_file_id"] for one in files] == ["F1", "F2"]
    assert all(one["fetch_state"] == "pending" for one in files)


def test_a_link_preview_brings_no_files_along():
    event = {"attachments": [{"is_msg_unfurl": True, "files": [image_file("F3")]}]}

    assert parse.files(event) == []


def test_a_file_both_sent_and_forwarded_is_kept_once():
    event = {"files": [image_file("F1")], "attachments": [{"is_share": True, "files": [image_file("F1")]}]}

    assert len(parse.files(event)) == 1


def test_a_forwarded_file_is_flagged_as_forwarded():
    event = {"files": [image_file("F1")], "attachments": [{"is_share": True, "files": [image_file("F2")]}]}

    assert [one["forwarded"] for one in parse.files(event)] == [False, True]


def test_forwarded_files_stay_out_of_the_reporters_own_post():
    from bot.nemo import attachments, channel

    assert "NOT mf.forwarded" in attachments.TO_SHARE
    for query in (channel.HAS_UNMIRRORED_CONTENT, channel.FILES_WAITING, channel.FILES_ON_CASE):
        assert "NOT mf.forwarded" in query
