import threading
from contextlib import contextmanager

from lib import build
from lib.db import connect, record_heartbeat

BEAT_SECONDS = 60
STALE_BUILD_STATE = "paused, old build"
STALE_BUILD_RECHECK_SECONDS = 60
build_state = {"newest": None}


def record(worker, note):
    try:
        with connect() as conn:
            record_heartbeat(conn, worker, note)
            build_state["newest"] = build.record_build(conn, worker)
    except Exception as exc:
        print(f"{worker}: heartbeat failed, {type(exc).__name__}: {exc}")


def on_stale_build():
    return build_state["newest"] not in (None, build.fingerprint())


def pause_stale_lane(worker, name, state, stopping):
    if not on_stale_build():
        return False
    if state.get(name) != STALE_BUILD_STATE:
        print(f"{worker}: {name} lane paused, build {build.fingerprint()} behind {build_state['newest']}")
    state[name] = STALE_BUILD_STATE
    stopping.wait(STALE_BUILD_RECHECK_SECONDS)
    return True


@contextmanager
def heartbeat_loop(worker, note, every=BEAT_SECONDS):
    stop = threading.Event()

    def record_beat():
        record(worker, note() if callable(note) else note)

    def beat_loop():
        while not stop.wait(every):
            record_beat()

    record_beat()
    thread = threading.Thread(target=beat_loop, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)
