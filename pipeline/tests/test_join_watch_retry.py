import contextlib

import pytest
from psycopg.errors import LockNotAvailable

from bot.nemo import new_members
from bot.nemo.surface import join_watch

USER = {"id": "U1", "profile": {}}


class Ctx:
    def __init__(self, user):
        self.payload = {"user": user}


@pytest.fixture
def world(monkeypatch):
    seen = {"attempts": 0, "fail": 0, "sleeps": []}

    @contextlib.contextmanager
    def session():
        yield object()

    def upsert(conn, user):
        seen["attempts"] += 1
        if seen["attempts"] <= seen["fail"]:
            raise LockNotAvailable("canceling statement due to lock timeout")
        return user["id"]

    monkeypatch.setattr(join_watch, "session", session)
    monkeypatch.setattr(new_members, "upsert_member", upsert)
    monkeypatch.setattr(join_watch.time, "sleep", seen["sleeps"].append)
    return seen


def test_upsert_with_retry_succeeds_first_time_without_sleeping(world):
    assert join_watch.upsert_with_retry(USER) == "U1"
    assert world["attempts"] == 1 and world["sleeps"] == []


def test_upsert_with_retry_retries_after_lock_timeout(world):
    world["fail"] = 2

    assert join_watch.upsert_with_retry(USER) == "U1"

    assert world["attempts"] == 3 and world["sleeps"] == list(join_watch.LOCK_RETRY_DELAYS_SECONDS[:2])


def test_upsert_with_retry_raises_when_lock_never_clears(world):
    world["fail"] = 99

    with pytest.raises(LockNotAvailable):
        join_watch.upsert_with_retry(USER)

    assert world["attempts"] == len(join_watch.LOCK_RETRY_DELAYS_SECONDS) + 1
    assert world["sleeps"] == list(join_watch.LOCK_RETRY_DELAYS_SECONDS)


def test_upsert_with_retry_other_errors_are_not_retried(world, monkeypatch):
    def broken(conn, user):
        world["attempts"] += 1
        raise ValueError("bad row")

    monkeypatch.setattr(new_members, "upsert_member", broken)

    with pytest.raises(ValueError):
        join_watch.upsert_with_retry(USER)

    assert world["attempts"] == 1 and world["sleeps"] == []


def test_record_user_change_retries_and_returns_user_id(world):
    world["fail"] = 1

    assert join_watch.record_user_change(Ctx(USER)) == "U1"
    assert world["attempts"] == 2


def test_record_user_change_without_user_does_nothing(world):
    assert join_watch.record_user_change(Ctx(None)) is None
    assert world["attempts"] == 0
