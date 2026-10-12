import threading
from contextlib import contextmanager

from lib import build
from lib.db import connect, record_heartbeat

BEAT_SECONDS = 60
HELD = "held, old build"
HELD_POLL_SECONDS = 60
newest = {"build": None}


def record(worker, note):
    try:
        with connect() as conn:
            record_heartbeat(conn, worker, note)
            newest["build"] = build.keep(conn, worker)
    except Exception as exc:
        print(f"{worker}: heartbeat failed, {type(exc).__name__}: {exc}")


def behind():
    return newest["build"] not in (None, build.fingerprint())


def hold(worker, name, state, stopping):
    if not behind():
        return False
    if state.get(name) != HELD:
        print(f"{worker}: the {name} lane is held, build {build.fingerprint()} is behind {newest['build']}")
    state[name] = HELD
    stopping.wait(HELD_POLL_SECONDS)
    return True


@contextmanager
def heartbeat_loop(worker, note, every=BEAT_SECONDS):
    stop = threading.Event()

    def beat():
        record(worker, note() if callable(note) else note)

    def tick():
        while not stop.wait(every):
            beat()

    beat()
    thread = threading.Thread(target=tick, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=5)
