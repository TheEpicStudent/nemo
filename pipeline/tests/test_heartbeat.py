import time

from lib import heartbeat


def test_beating_pulses_on_its_own_thread_and_evaluates_a_callable_note(monkeypatch):
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


def test_beating_stops_when_the_block_exits(monkeypatch):
    records = []
    monkeypatch.setattr(heartbeat, "record", lambda worker, note: records.append(note))
    with heartbeat.heartbeat_loop("w", "hello", every=0.01):
        time.sleep(0.03)
    baseline_count = len(records)
    time.sleep(0.05)
    assert len(records) == baseline_count


def test_a_plain_string_note_is_passed_through(monkeypatch):
    records = []
    monkeypatch.setattr(heartbeat, "record", lambda worker, note: records.append(note))
    with heartbeat.heartbeat_loop("w", "idle", every=0.01):
        time.sleep(0.02)
    assert records and all(n == "idle" for n in records)


def test_the_first_beat_lands_before_the_block_runs(monkeypatch):
    records = []
    monkeypatch.setattr(heartbeat, "record", lambda worker, note: records.append(note))

    with heartbeat.heartbeat_loop("w", "starting", every=60):
        assert records == ["starting"]


def test_a_beat_keeps_the_newest_build_it_reads(monkeypatch):
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


def test_a_worker_is_behind_only_when_a_newer_build_is_known(monkeypatch):
    monkeypatch.setattr(heartbeat.build, "fingerprint", lambda: "abc123abc123")

    monkeypatch.setitem(heartbeat.build_state, "newest", None)
    assert not heartbeat.on_stale_build()
    monkeypatch.setitem(heartbeat.build_state, "newest", "abc123abc123")
    assert not heartbeat.on_stale_build()
    monkeypatch.setitem(heartbeat.build_state, "newest", "def456def456")
    assert heartbeat.on_stale_build()


def test_a_lane_on_an_old_build_is_held_and_says_so_once(monkeypatch, capsys):
    import threading

    monkeypatch.setattr(heartbeat.build, "fingerprint", lambda: "abc123abc123")
    monkeypatch.setitem(heartbeat.build_state, "newest", "def456def456")
    monkeypatch.setattr(heartbeat, "STALE_BUILD_RECHECK_SECONDS", 0)
    state = {"links_live": "idle"}

    assert heartbeat.pause_stale_lane("audit_worker", "links_live", state, threading.Event())
    assert heartbeat.pause_stale_lane("audit_worker", "links_live", state, threading.Event())

    assert state["links_live"] == "held, old build"
    assert capsys.readouterr().out.count("the links_live lane is held") == 1


def test_a_lane_on_the_newest_build_is_not_held(monkeypatch):
    import threading

    monkeypatch.setattr(heartbeat.build, "fingerprint", lambda: "abc123abc123")
    monkeypatch.setitem(heartbeat.build_state, "newest", "abc123abc123")
    state = {"links_live": "idle"}

    assert not heartbeat.pause_stale_lane("audit_worker", "links_live", state, threading.Event())
    assert state["links_live"] == "idle"
