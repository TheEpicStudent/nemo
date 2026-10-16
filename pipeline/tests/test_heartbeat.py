import time

from lib import heartbeat


def test_heartbeat_loop_callable_note_is_evaluated_each_beat(monkeypatch):
    records = []
    monkeypatch.setattr(heartbeat, "record", lambda worker, note: records.append((worker, note)))
    state = {"n": 0}

    with heartbeat.heartbeat_loop("test_worker", lambda: f"draining {state['n']}", every=0.01):
        time.sleep(0.05)
        state["n"] = 3
        time.sleep(0.05)

    assert len(records) >= 3
    assert records[0] == ("test_worker", "draining 0")
    assert ("test_worker", "draining 3") in records


def test_heartbeat_loop_after_exit_stops_recording(monkeypatch):
    records = []
    monkeypatch.setattr(heartbeat, "record", lambda worker, note: records.append(note))
    with heartbeat.heartbeat_loop("w", "hello", every=0.01):
        time.sleep(0.03)
    baseline_count = len(records)
    time.sleep(0.05)
    assert len(records) == baseline_count


def test_heartbeat_loop_string_note_is_recorded_unchanged(monkeypatch):
    records = []
    monkeypatch.setattr(heartbeat, "record", lambda worker, note: records.append(note))
    with heartbeat.heartbeat_loop("w", "idle", every=0.01):
        time.sleep(0.02)
    assert records and all(n == "idle" for n in records)


def test_heartbeat_loop_records_first_beat_before_body_runs(monkeypatch):
    records = []
    monkeypatch.setattr(heartbeat, "record", lambda worker, note: records.append(note))

    with heartbeat.heartbeat_loop("w", "starting", every=60):
        assert records == ["starting"]


def test_record_stores_newest_build_in_build_state(monkeypatch):
    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    monkeypatch.setattr(heartbeat, "connect", Conn)
    monkeypatch.setattr(heartbeat, "record_heartbeat", lambda conn, worker, note: None)
    monkeypatch.setattr(heartbeat.build, "record_build", lambda conn, worker: "def456def456")
    monkeypatch.setitem(heartbeat.build_state, "newest", None)

    heartbeat.record("audit_worker", "idle")

    assert heartbeat.build_state["newest"] == "def456def456"


def test_on_stale_build_is_true_only_when_newer_build_known(monkeypatch):
    monkeypatch.setattr(heartbeat.build, "fingerprint", lambda: "abc123abc123")

    monkeypatch.setitem(heartbeat.build_state, "newest", None)
    assert not heartbeat.on_stale_build()
    monkeypatch.setitem(heartbeat.build_state, "newest", "abc123abc123")
    assert not heartbeat.on_stale_build()
    monkeypatch.setitem(heartbeat.build_state, "newest", "def456def456")
    assert heartbeat.on_stale_build()


def test_pause_stale_lane_old_build_pauses_and_prints_once(monkeypatch, capsys):
    import threading

    monkeypatch.setattr(heartbeat.build, "fingerprint", lambda: "abc123abc123")
    monkeypatch.setitem(heartbeat.build_state, "newest", "def456def456")
    monkeypatch.setattr(heartbeat, "STALE_BUILD_RECHECK_SECONDS", 0)
    state = {"links_live": "idle"}

    assert heartbeat.pause_stale_lane("audit_worker", "links_live", state, threading.Event())
    assert heartbeat.pause_stale_lane("audit_worker", "links_live", state, threading.Event())

    assert state["links_live"] == "paused, old build"
    assert capsys.readouterr().out.count("links_live lane paused") == 1


def test_pause_stale_lane_newest_build_does_not_pause(monkeypatch):
    import threading

    monkeypatch.setattr(heartbeat.build, "fingerprint", lambda: "abc123abc123")
    monkeypatch.setitem(heartbeat.build_state, "newest", "abc123abc123")
    state = {"links_live": "idle"}

    assert not heartbeat.pause_stale_lane("audit_worker", "links_live", state, threading.Event())
    assert state["links_live"] == "idle"
