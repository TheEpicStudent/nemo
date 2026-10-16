from datetime import datetime, timezone

from jobs import member_history_worker
from lib import settings


def at(hour):
    return datetime(2026, 10, 7, hour, 0, tzinfo=timezone.utc)


def install_fakes(monkeypatch, last_ok_times):
    prepare_calls = []
    monkeypatch.setattr(settings, "last_ok", lambda conn, key: last_ok_times.get(key))
    monkeypatch.setattr(member_history_worker, "prepare_member_history",
                        lambda conn: prepare_calls.append(conn) or 3)
    return prepare_calls


def test_prepare_if_new_without_previous_run_prepares_and_returns_newest_input(monkeypatch):
    prepare_calls = install_fakes(monkeypatch, {"member_days": at(3), "member_range": at(4), "users_list": at(5)})

    assert member_history_worker.prepare_if_new("conn", None) == at(5)
    assert prepare_calls == ["conn"]


def test_prepare_if_new_unchanged_inputs_skips_prepare(monkeypatch):
    prepare_calls = install_fakes(monkeypatch, {"member_days": at(3), "member_range": at(4), "users_list": at(5)})

    assert member_history_worker.prepare_if_new("conn", at(5)) == at(5)
    assert prepare_calls == []


def test_prepare_if_new_one_newer_input_prepares(monkeypatch):
    prepare_calls = install_fakes(monkeypatch, {"member_days": at(6), "member_range": at(4), "users_list": at(5)})

    assert member_history_worker.prepare_if_new("conn", at(5)) == at(6)
    assert prepare_calls == ["conn"]


def test_prepare_if_new_without_input_timestamps_prepares_and_returns_none(monkeypatch):
    prepare_calls = install_fakes(monkeypatch, {})

    assert member_history_worker.prepare_if_new("conn", None) is None
    assert prepare_calls == ["conn"]
