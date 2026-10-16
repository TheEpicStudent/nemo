import threading

from bot.core import loops


class Counter:
    def __init__(self, answers=()):
        self.answers = list(answers)
        self.run_count = 0
        self.run_signal = threading.Semaphore(0)

    def __call__(self):
        self.run_count += 1
        self.run_signal.release()
        return self.answers.pop(0) if self.answers else False


def start_loop(work, stopping, debounce_seconds=0.05):
    return loops.run_on_wake("test", work, stopping, debounce_seconds=debounce_seconds, interval_seconds=30)


def test_run_on_wake_on_start_runs_work_once():
    stopping, work = threading.Event(), Counter()
    wake = start_loop(work, stopping)

    assert work.run_signal.acquire(timeout=1)
    assert not work.run_signal.acquire(timeout=0.2)
    stopping.set()
    wake()


def test_run_on_wake_burst_of_wakes_runs_work_once_after_start():
    stopping, work = threading.Event(), Counter()
    wake = start_loop(work, stopping)
    assert work.run_signal.acquire(timeout=1)

    for _ in range(5):
        wake()

    assert work.run_signal.acquire(timeout=1)
    assert not work.run_signal.acquire(timeout=0.3)
    assert work.run_count == 2
    stopping.set()
    wake()


def test_run_on_wake_work_returning_true_reruns_without_wake():
    stopping, work = threading.Event(), Counter(answers=[True, True, False])
    wake = start_loop(work, stopping)

    for _ in range(3):
        assert work.run_signal.acquire(timeout=1)
    assert not work.run_signal.acquire(timeout=0.2)
    stopping.set()
    wake()


def test_run_on_wake_raising_work_does_not_stop_loop():
    stopping = threading.Event()
    run_signal = threading.Semaphore(0)
    calls = []

    def work():
        calls.append(1)
        run_signal.release()
        if len(calls) == 1:
            raise RuntimeError("database went away")
        return False

    wake = start_loop(work, stopping)
    assert run_signal.acquire(timeout=1)
    wake()
    assert run_signal.acquire(timeout=1)
    stopping.set()
    wake()


def test_run_on_wake_stop_during_debounce_skips_pending_run():
    stopping, work = threading.Event(), Counter()
    wake = start_loop(work, stopping, debounce_seconds=0.2)
    assert work.run_signal.acquire(timeout=1)

    wake()
    stopping.set()

    assert not work.run_signal.acquire(timeout=0.4)
