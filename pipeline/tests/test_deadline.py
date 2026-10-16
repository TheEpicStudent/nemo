import time

from lib.deadline import Deadline


def test_deadline_after_timeout_is_expired_with_zero_remaining():
    d = Deadline(0.05)
    assert not d.expired()
    assert 0 < d.remaining() <= 0.05
    time.sleep(0.06)
    assert d.expired()
    assert d.remaining() == 0.0


def test_deadline_clamp_limits_value_to_remaining_time():
    d = Deadline(0.5)
    assert d.clamp(60) <= 0.5
    assert d.clamp(0.1) <= 0.1
    assert Deadline(0).clamp(10) == 0.0
