import pytest

from lib import task
from lib.db import RunCounts
from lib.proxy_client import InternalApiError, ProxyUnavailableError


class FakeConn:
    def __init__(self):
        self.rollbacks = 0
        self.commits = 0

    def rollback(self):
        self.rollbacks += 1

    def commit(self):
        self.commits += 1


@pytest.fixture
def stub_dead_letter(monkeypatch):
    dead_letters = []
    monkeypatch.setattr(task, "dead_letter", lambda conn, source, payload, reason: dead_letters.append((source, payload, reason)))
    return dead_letters


def test_per_entity_upstream_fault_dead_letters_and_continues(stub_dead_letter):
    conn, counts = FakeConn(), RunCounts()
    with task.per_entity(conn, "member_history", counts, {"user_id": "U1"}):
        raise InternalApiError("internal_error")
    assert counts.rows_rejected == 1
    assert conn.rollbacks == 1
    assert stub_dead_letter == [("member_history", {"user_id": "U1"}, "upstream: internal_error")]


def test_per_entity_transport_fault_raises_proxy_unavailable(stub_dead_letter):
    conn, counts = FakeConn(), RunCounts()
    with pytest.raises(ProxyUnavailableError):
        with task.per_entity(conn, "member_history", counts, {"user_id": "U1"}):
            raise ProxyUnavailableError("proxy unreachable")
    assert counts.rows_rejected == 0
    assert stub_dead_letter == []


def test_per_entity_entity_fault_calls_on_entity_without_dead_letter(stub_dead_letter):
    conn, counts, handled = FakeConn(), RunCounts(), []
    with task.per_entity(conn, "member_history", counts, {"user_id": "U1"}, on_entity=handled.append):
        raise InternalApiError("channel_not_found")
    assert [f.name for f in handled] == ["entity"]
    assert stub_dead_letter == []
    assert counts.rows_rejected == 0


def test_per_entity_on_fault_receives_contract_fault(stub_dead_letter):
    conn, counts, faults = FakeConn(), RunCounts(), []
    with task.per_entity(conn, "channel_history", counts, {"channel_id": "C1"}, on_fault=faults.append):
        raise KeyError("ts")
    assert [f.name for f in faults] == ["contract"]
    assert counts.rows_rejected == 1


def test_per_entity_clean_entity_resets_consecutive_faults(stub_dead_letter):
    conn, counts = FakeConn(), RunCounts(consecutive_faults=7)
    with task.per_entity(conn, "x", counts, {}):
        pass
    assert counts.consecutive_faults == 0


def test_per_entity_consecutive_upstream_faults_at_cap_raises_lane_aborted(stub_dead_letter):
    conn, counts = FakeConn(), RunCounts()
    with pytest.raises(task.LaneAbortedError) as caught:
        for _ in range(task.CONSECUTIVE_FAULTS):
            with task.per_entity(conn, "channel_membership", counts, {"user_id": "U"}):
                raise InternalApiError("internal_error")
    assert f"{task.CONSECUTIVE_FAULTS} consecutive upstream faults" in str(caught.value)
    assert len(stub_dead_letter) == task.CONSECUTIVE_FAULTS
