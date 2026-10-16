import threading
import time

from jobs import audit_worker


def lane_names(lanes):
    return [name for name, *_ in lanes]


def test_lane_enabled_backfill_unset_returns_true(monkeypatch):
    monkeypatch.delenv("AUDIT_BACKFILL", raising=False)

    assert audit_worker.lane_enabled("backfill")


def test_lane_enabled_access_backfill_unset_returns_false(monkeypatch):
    monkeypatch.delenv("AUDIT_ACCESS_BACKFILL", raising=False)

    assert not audit_worker.lane_enabled("access_backfill")


def test_lane_enabled_without_switch_returns_true():
    assert audit_worker.lane_enabled("tail")
    assert audit_worker.lane_enabled("access")


def test_lane_enabled_switch_value_case_is_ignored(monkeypatch):
    for value in ("0", "off", "No", " FALSE "):
        monkeypatch.setenv("AUDIT_BACKFILL", value)
        assert not audit_worker.lane_enabled("backfill"), value

    for value in ("1", "on", "yes", "true"):
        monkeypatch.setenv("AUDIT_ACCESS_BACKFILL", value)
        assert audit_worker.lane_enabled("access_backfill"), value


def test_enabled_lanes_switched_off_lanes_are_excluded(monkeypatch):
    monkeypatch.setenv("AUDIT_BACKFILL", "off")
    monkeypatch.delenv("AUDIT_ACCESS_BACKFILL", raising=False)

    names = lane_names(audit_worker.enabled_lanes())

    assert "backfill" not in names
    assert "access_backfill" not in names
    assert names[0] == "tail"


def test_enabled_lanes_all_switches_on_returns_all_lanes(monkeypatch):
    monkeypatch.delenv("AUDIT_BACKFILL", raising=False)
    monkeypatch.setenv("AUDIT_ACCESS_BACKFILL", "on")
    monkeypatch.delenv("AUDIT_BACKFILL_SETS", raising=False)

    names = lane_names(audit_worker.enabled_lanes())

    assert names == lane_names(audit_worker.LANES)


def test_lane_notify_channels_map_clusters_and_links_live():
    assert audit_worker.LANE_NOTIFY_CHANNELS == {"clusters": "fd_member_link", "links_live": "fd_member_touch"}
    assert audit_worker.NOTIFY_DEBOUNCE_SECONDS == 2


def test_lane_notify_events_notification_sets_only_its_lane_event(monkeypatch):
    listen_args = {}
    monkeypatch.setattr(audit_worker.loops, "start_listener",
                        lambda _name, channels, on_notify, _stopping: listen_args.update(channels=channels, on_notify=on_notify))

    events = audit_worker.lane_notify_events(audit_worker.LANES, threading.Event())

    assert sorted(events) == ["clusters", "links_live"]
    assert listen_args["channels"] == ("fd_member_link", "fd_member_touch")
    listen_args["on_notify"]("fd_member_link", "*")
    assert events["clusters"].is_set() and not events["links_live"].is_set()
    events["clusters"].clear()
    listen_args["on_notify"]("fd_member_touch", "*")
    assert events["links_live"].is_set() and not events["clusters"].is_set()


def test_member_touch_migration_notifies_per_statement_without_delete():
    import pathlib

    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0221_member_touch_notify.sql").read_text()
    assert "PERFORM pg_notify('fd_member_touch', '*')" in sql
    assert "AFTER INSERT OR UPDATE ON fd.member_touch" in sql
    assert "FOR EACH STATEMENT" in sql
    assert "DELETE" not in sql.split("CREATE TRIGGER")[1]


def test_wait_for_next_pass_wake_set_returns_false_and_clears_wake(monkeypatch):
    monkeypatch.setattr(audit_worker, "NOTIFY_DEBOUNCE_SECONDS", 0.01)
    stopping, wake = threading.Event(), threading.Event()
    wake.set()
    start_time = time.monotonic()

    assert audit_worker.wait_for_next_pass(stopping, wake, 3600) is False
    assert time.monotonic() - start_time < 1
    assert not wake.is_set()


def test_wait_for_next_pass_wake_unset_waits_poll_interval():
    stopping, wake = threading.Event(), threading.Event()
    start_time = time.monotonic()

    assert audit_worker.wait_for_next_pass(stopping, wake, 0.05) is False
    assert time.monotonic() - start_time >= 0.05


def test_wait_for_next_pass_wake_unset_returns_true_when_stopping():
    stopping, wake = threading.Event(), threading.Event()
    threading.Timer(0.05, stopping.set).start()
    start_time = time.monotonic()

    assert audit_worker.wait_for_next_pass(stopping, wake, 3600) is True
    assert time.monotonic() - start_time < 2


def test_wait_for_next_pass_without_wake_returns_true_when_stopping():
    stopping = threading.Event()
    stopping.set()

    assert audit_worker.wait_for_next_pass(stopping, None, 3600) is True


def test_lane_old_build_does_not_run_work(monkeypatch):
    from lib import heartbeat

    calls = []
    stopping = threading.Event()
    monkeypatch.setattr(heartbeat.build, "fingerprint", lambda: "abc123abc123")
    monkeypatch.setitem(heartbeat.build_state, "newest", "def456def456")
    monkeypatch.setattr(heartbeat, "STALE_BUILD_RECHECK_SECONDS", 0.01)
    state = {"links_live": "starting"}

    thread = audit_worker.lane("links_live", calls.append, state, stopping, 3600)
    time.sleep(0.1)
    lane_state = state["links_live"]
    stopping.set()
    thread.join(timeout=2)

    assert calls == []
    assert lane_state == "paused, old build"


def test_tail_lane_default_poll_is_5_seconds():
    assert audit_worker.DEFAULT_TAIL_SECONDS == 5
    assert ("tail", audit_worker.walk_tail, "AUDIT_TAIL_SECONDS", 5, True) in audit_worker.LANES
