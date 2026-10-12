import threading
import time

from jobs import audit_worker


def lane_names(lanes):
    return [name for name, *_ in lanes]


def test_the_audit_backfill_lane_is_on_by_default(monkeypatch):
    monkeypatch.delenv("AUDIT_BACKFILL", raising=False)

    assert audit_worker.lane_enabled("backfill")


def test_the_access_backfill_lane_is_off_by_default(monkeypatch):
    monkeypatch.delenv("AUDIT_ACCESS_BACKFILL", raising=False)

    assert not audit_worker.lane_enabled("access_backfill")


def test_lanes_without_a_switch_always_run():
    assert audit_worker.lane_enabled("tail")
    assert audit_worker.lane_enabled("access")


def test_switch_values_are_read_case_insensitively(monkeypatch):
    for value in ("0", "off", "No", " FALSE "):
        monkeypatch.setenv("AUDIT_BACKFILL", value)
        assert not audit_worker.lane_enabled("backfill"), value

    for value in ("1", "on", "yes", "true"):
        monkeypatch.setenv("AUDIT_ACCESS_BACKFILL", value)
        assert audit_worker.lane_enabled("access_backfill"), value


def test_wanted_lanes_leaves_out_switched_off_lanes(monkeypatch):
    monkeypatch.setenv("AUDIT_BACKFILL", "off")
    monkeypatch.delenv("AUDIT_ACCESS_BACKFILL", raising=False)

    names = lane_names(audit_worker.wanted_lanes())

    assert "backfill" not in names
    assert "access_backfill" not in names
    assert names[0] == "tail"


def test_wanted_lanes_runs_every_lane_when_every_switch_is_on(monkeypatch):
    monkeypatch.delenv("AUDIT_BACKFILL", raising=False)
    monkeypatch.setenv("AUDIT_ACCESS_BACKFILL", "on")
    monkeypatch.delenv("AUDIT_BACKFILL_SETS", raising=False)

    names = lane_names(audit_worker.wanted_lanes())

    assert names == lane_names(audit_worker.LANES)


def test_the_cluster_lane_wakes_on_link_changes():
    assert audit_worker.WAKES == {"clusters": "fd_member_link"}
    assert audit_worker.SETTLE_SECONDS == 2


def test_link_notifications_wake_only_the_cluster_lane(monkeypatch):
    held = {}
    monkeypatch.setattr(audit_worker.loops, "watching",
                        lambda _name, channels, ring, _stopping: held.update(channels=channels, ring=ring))

    events = audit_worker.wakes_for(audit_worker.LANES, threading.Event())

    assert list(events) == ["clusters"]
    assert held["channels"] == ("fd_member_link",)
    held["ring"]("fd_member_link", "*")
    assert events["clusters"].is_set()


def test_a_woken_lane_runs_again_after_the_settle(monkeypatch):
    monkeypatch.setattr(audit_worker, "SETTLE_SECONDS", 0.01)
    stopping, wake = threading.Event(), threading.Event()
    wake.set()
    started = time.monotonic()

    assert audit_worker.rest(stopping, wake, 3600) is False
    assert time.monotonic() - started < 1
    assert not wake.is_set()


def test_an_unwoken_lane_waits_out_its_poll():
    stopping, wake = threading.Event(), threading.Event()
    started = time.monotonic()

    assert audit_worker.rest(stopping, wake, 0.05) is False
    assert time.monotonic() - started >= 0.05


def test_a_lane_waiting_for_a_wake_still_stops():
    stopping, wake = threading.Event(), threading.Event()
    threading.Timer(0.05, stopping.set).start()
    started = time.monotonic()

    assert audit_worker.rest(stopping, wake, 3600) is True
    assert time.monotonic() - started < 2


def test_a_lane_without_a_wake_waits_on_stopping_alone():
    stopping = threading.Event()
    stopping.set()

    assert audit_worker.rest(stopping, None, 3600) is True
