from bot.core import parse


def image_file(file_id):
    return {"id": file_id, "name": "image.png", "mimetype": "image/png", "mode": "hosted",
            "url_private": f"https://files.slack.com/{file_id}/image.png"}


def test_files_forwarded_image_is_included_with_direct_files():
    event = {"files": [image_file("F1")], "attachments": [
        {"is_share": True, "files": [image_file("F2")]},
    ]}

    files = parse.files(event)

    assert [one["slack_file_id"] for one in files] == ["F1", "F2"]
    assert all(one["fetch_state"] == "pending" for one in files)


def test_files_link_unfurl_returns_empty():
    event = {"attachments": [{"is_msg_unfurl": True, "files": [image_file("F3")]}]}

    assert parse.files(event) == []


def test_files_duplicate_direct_and_forwarded_returns_one():
    event = {"files": [image_file("F1")], "attachments": [{"is_share": True, "files": [image_file("F1")]}]}

    assert len(parse.files(event)) == 1


def test_files_forwarded_attachment_sets_forwarded_flag():
    event = {"files": [image_file("F1")], "attachments": [{"is_share": True, "files": [image_file("F2")]}]}

    assert [one["forwarded"] for one in parse.files(event)] == [False, True]


def test_unmirrored_file_queries_exclude_forwarded_files():
    from bot.nemo import attachments, channel

    assert "NOT mf.forwarded" in attachments.UNMIRRORED_FILES
    for query in (channel.HAS_UNMIRRORED_CONTENT, channel.FILES_WAITING, channel.FILES_ON_CASE):
        assert "NOT mf.forwarded" in query
