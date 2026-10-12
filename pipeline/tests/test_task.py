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


def test_an_upstream_fault_is_dead_lettered_and_the_loop_continues(stub_dead_letter):
    conn, counts = FakeConn(), RunCounts()
    with task.per_entity(conn, "member_history", counts, {"user_id": "U1"}):
        raise InternalApiError("internal_error")
    assert counts.rows_rejected == 1
    assert conn.rollbacks == 1
    assert stub_dead_letter == [("member_history", {"user_id": "U1"}, "upstream: internal_error")]


def test_a_transport_fault_aborts_the_lane(stub_dead_letter):
    conn, counts = FakeConn(), RunCounts()
    with pytest.raises(ProxyUnavailableError):
        with task.per_entity(conn, "member_history", counts, {"user_id": "U1"}):
            raise ProxyUnavailableError("proxy unreachable")
    assert counts.rows_rejected == 0
    assert stub_dead_letter == []


def test_an_entity_fault_goes_to_the_handler_instead_of_the_dead_letter(stub_dead_letter):
    conn, counts, handled = FakeConn(), RunCounts(), []
    with task.per_entity(conn, "member_history", counts, {"user_id": "U1"}, on_entity=handled.append):
        raise InternalApiError("channel_not_found")
    assert [f.name for f in handled] == ["entity"]
    assert stub_dead_letter == []
    assert counts.rows_rejected == 0


def test_on_fault_sees_every_continued_fault(stub_dead_letter):
    conn, counts, faults = FakeConn(), RunCounts(), []
    with task.per_entity(conn, "channel_history", counts, {"channel_id": "C1"}, on_fault=faults.append):
        raise KeyError("ts")
    assert [f.name for f in faults] == ["contract"]
    assert counts.rows_rejected == 1


def test_a_clean_entity_resets_the_consecutive_counter(stub_dead_letter):
    conn, counts = FakeConn(), RunCounts(consecutive_faults=7)
    with task.per_entity(conn, "x", counts, {}):
        pass
    assert counts.consecutive_faults == 0


def test_the_same_outage_is_not_dead_lettered_forever(stub_dead_letter):
    conn, counts = FakeConn(), RunCounts()
    with pytest.raises(task.LaneAbortedError) as caught:
        for _ in range(task.CONSECUTIVE_FAULTS):
            with task.per_entity(conn, "channel_membership", counts, {"user_id": "U"}):
                raise InternalApiError("internal_error")
    assert f"{task.CONSECUTIVE_FAULTS} consecutive upstream faults" in str(caught.value)
    assert len(stub_dead_letter) == task.CONSECUTIVE_FAULTS
