import threading
import time

from jobs import archive_worker


def test_an_archive_lane_on_an_old_build_never_runs_its_work(monkeypatch):
    from lib import heartbeat

    ran = []
    stopping = threading.Event()
    monkeypatch.setattr(heartbeat.build, "fingerprint", lambda: "abc123abc123")
    monkeypatch.setitem(heartbeat.newest, "build", "def456def456")
    monkeypatch.setattr(heartbeat, "HELD_POLL_SECONDS", 0.01)
    state = {"history": "starting"}

    thread = archive_worker.lane("history", ran.append, state, stopping, 300)
    time.sleep(0.1)
    held = state["history"]
    stopping.set()
    thread.join(timeout=2)

    assert ran == []
    assert held == "held, old build"
