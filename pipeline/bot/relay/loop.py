import logging
import os

from bot.core import loops, outbox, session
from bot.relay import hourglass

log = logging.getLogger("bot.relay")

NAME = "relay"
OUTBOX = "fd_outbox_waiting"
CASES = "fd_case_changed"
DEFAULT_SECONDS = 300


def every():
    return int(os.environ.get("RELAY_SWEEP_SECONDS", DEFAULT_SECONDS))


def once(relay):
    with session() as conn:
        queued = outbox.any_waiting(conn)

    delivered = sum(relay.deliver(conversation_id) for conversation_id in queued)
    hourglass.release(relay.client)
    return delivered


def start(relay, stopping):
    def on_notify(channel_name, payload):
        if channel_name == CASES:
            hourglass.release(relay.client, payload)
        else:
            relay.deliver(payload)

    return (
        loops.start_listener(NAME, (OUTBOX, CASES), on_notify, stopping),
        loops.run_periodically(NAME, every(), lambda: once(relay), stopping),
    )
