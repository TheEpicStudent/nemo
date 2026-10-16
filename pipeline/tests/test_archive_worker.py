import threading
import time

from jobs import archive_worker


def test_lane_on_old_build_does_not_run_work(monkeypatch):
    from lib import heartbeat

    calls = []
    stopping = threading.Event()
    monkeypatch.setattr(heartbeat.build, "fingerprint", lambda: "abc123abc123")
    monkeypatch.setitem(heartbeat.build_state, "newest", "def456def456")
    monkeypatch.setattr(heartbeat, "STALE_BUILD_RECHECK_SECONDS", 0.01)
    state = {"history": "starting"}

    thread = archive_worker.lane("history", calls.append, state, stopping, 300)
    time.sleep(0.1)
    lane_state = state["history"]
    stopping.set()
    thread.join(timeout=2)

    assert calls == []
    assert lane_state == "paused, old build"
