import logging
import threading

from lib.db import connect

log = logging.getLogger("bot.loops")

RETRY_SECONDS = 5


def listen(name, channels, on_notify, stopping):
    conn = connect()
    conn.autocommit = True
    for channel_name in channels:
        conn.execute(f"LISTEN {channel_name}")
    log.info("%s: listening for %s", name, ", ".join(channels))

    try:
        for notification in conn.notifies(stop_after=None, timeout=None):
            if stopping.is_set():
                break
            payload = int(notification.payload) if notification.payload.isdigit() else notification.payload
            if not payload:
                continue
            try:
                on_notify(notification.channel, payload)
            except Exception as failure:
                log.warning("%s: %s %s could not be handled: %s",
                            name, notification.channel, payload, failure)
    finally:
        try:
            conn.close()
        except Exception:
            pass


def start_listener(name, channels, on_notify, stopping):
    def loop():
        while not stopping.is_set():
            try:
                listen(name, channels, on_notify, stopping)
            except Exception as failure:
                log.warning("%s: lost the listener, waiting to retry: %s", name, failure)
                if stopping.wait(RETRY_SECONDS):
                    return

    thread = threading.Thread(target=loop, name=f"{name}-watch", daemon=True)
    thread.start()
    return thread


def run_periodically(name, seconds, work, stopping):
    def loop():
        log.info("%s: catching up on anything missed, then sweeping every %ss", name, seconds)
        while True:
            try:
                work()
            except Exception:
                log.exception("%s: the sweep failed, trying again next time", name)
            if stopping.wait(seconds):
                return

    thread = threading.Thread(target=loop, name=f"{name}-sweep", daemon=True)
    thread.start()
    return thread


def run_on_wake(name, work, stopping, debounce_seconds=2.0, interval_seconds=60.0):
    wake = threading.Event()

    def loop():
        while not stopping.is_set():
            try:
                more = work()
            except Exception:
                log.exception("%s: the drain failed, trying again next time", name)
                more = False
            if more:
                continue
            if wake.wait(interval_seconds) and stopping.wait(debounce_seconds):
                return
            wake.clear()

    thread = threading.Thread(target=loop, name=f"{name}-drain", daemon=True)
    thread.start()
    return wake.set


def run_on_timer(name, work, stopping, max_wait_seconds=300.0, retry_seconds=30.0, debounce_seconds=0.5):
    wake = threading.Event()

    def loop():
        while not stopping.is_set():
            try:
                seconds = work()
            except Exception:
                log.exception("%s: the timed run failed, trying again later", name)
                seconds = retry_seconds
            if seconds is None:
                wait = max_wait_seconds
            elif seconds <= 0:
                wait = retry_seconds
            else:
                wait = min(seconds, max_wait_seconds)
            if wake.wait(wait) and stopping.wait(debounce_seconds):
                return
            wake.clear()

    thread = threading.Thread(target=loop, name=f"{name}-timer", daemon=True)
    thread.start()
    return wake.set
