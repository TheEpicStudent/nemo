import threading

from jobs import case_chat_import


def test_event_of_member_message():
    event = case_chat_import.event_of("C0FIRE", {"ts": "1.2", "thread_ts": "1.0", "user": "UONE",
                                                 "text": "hi", "blocks": [{"type": "rich_text"}]})
    assert event == {"channel": "C0FIRE", "ts": "1.2", "thread_ts": "1.0", "user": "UONE",
                     "text": "hi", "blocks": [{"type": "rich_text"}]}


def test_event_of_bot_message_without_user_uses_bot_id():
    event = case_chat_import.event_of("C0FIRE", {"ts": "1.3", "bot_id": "B0SHROUD", "text": "Case #4"})
    assert event["user"] == "B0SHROUD"
    assert event["blocks"] is None


def test_serve_waits_until_the_link_is_on_and_imported(monkeypatch):
    stopping = threading.Event()
    monkeypatch.setattr(case_chat_import, "ready", lambda: False)
    monkeypatch.setattr(case_chat_import, "run", lambda client: (_ for _ in ()).throw(AssertionError("ran")))
    monkeypatch.setattr(stopping, "wait", lambda seconds: stopping.set())
    case_chat_import.serve(None, stopping)
