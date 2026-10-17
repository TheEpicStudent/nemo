import contextlib

import pytest
from psycopg.errors import LockNotAvailable

from bot.nemo import case_channel


@pytest.fixture
def case_channel_steps(monkeypatch):
    @contextlib.contextmanager
    def fake_session():
        yield object()

    sleeps = []
    monkeypatch.setattr(case_channel, "session", fake_session)
    monkeypatch.setattr(case_channel.time, "sleep", sleeps.append)
    return sleeps


def test_run_step_retries_after_lock_timeout(case_channel_steps):
    attempts = []

    def work(client, conn, case_id):
        attempts.append(case_id)
        if len(attempts) < 3:
            raise LockNotAvailable("canceling statement due to lock timeout")
        return "done"

    assert case_channel.CaseChannel().run_step(work, 47) == "done"
    assert attempts == [47, 47, 47]
    assert case_channel_steps == list(case_channel.LOCK_RETRY_DELAYS_SECONDS)


def test_run_step_raises_when_lock_never_clears(case_channel_steps):
    def work(client, conn, case_id):
        raise LockNotAvailable("canceling statement due to lock timeout")

    with pytest.raises(LockNotAvailable):
        case_channel.CaseChannel().run_step(work, 47)
    assert len(case_channel_steps) == len(case_channel.LOCK_RETRY_DELAYS_SECONDS)


def test_run_step_does_not_retry_other_errors(case_channel_steps):
    def work(client, conn, case_id):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        case_channel.CaseChannel().run_step(work, 47)
    assert case_channel_steps == []
