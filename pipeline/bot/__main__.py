import argparse
import logging
import os
import signal
import sys
import threading

from dotenv import load_dotenv
from slack_bolt.adapter.socket_mode import SocketModeHandler

from bot import APPS, NEEDS, NEMO, RELAY
from bot.core import session, shutdown
from lib.config import DATABASE
from lib.db import SeededDeployment, refuse_if_seeded
from lib.heartbeat import heartbeat_loop
from lib.paths import ENV_FILE

log = logging.getLogger("bot")

WORKER = "bot"


def parse_args(argv):
    parser = argparse.ArgumentParser(prog="nemo bot")
    parser.add_argument(
        "apps",
        nargs="*",
        choices=APPS,
        help="app to run; both if unspecified",
    )
    return parser.parse_args(argv)


def missing_variables(apps):
    required_vars = list(DATABASE)
    for name in apps:
        required_vars += NEEDS[name]
    return [name for name in required_vars if not os.environ.get(name)]


def worker(apps):
    return ".".join([WORKER] + sorted(apps))


def app_list(apps):
    return " and ".join(apps)


def wire_relay(built, workers):
    from bot.relay import app as relay_app
    from bot.relay.messages import MessageRelay

    relay = MessageRelay()
    app = relay_app.build(relay.submit_report)
    relay.client = app.client
    built[RELAY] = (app, relay_app.app_token())
    workers[RELAY] = relay


def wire_nemo(built, workers):
    from bot.nemo import app as nemo_app
    from bot.nemo.case_channel import CaseChannel

    case_channel = CaseChannel()
    app = nemo_app.build(case_channel.queue_reply)
    case_channel.client = app.client
    built[NEMO] = (app, nemo_app.app_token())
    workers[NEMO] = case_channel


def wire(apps):
    built, workers = {}, {}
    if RELAY in apps:
        wire_relay(built, workers)
    if NEMO in apps:
        wire_nemo(built, workers)
    return built, workers


def start_loops(workers, stopping):
    if RELAY in workers:
        from bot.relay import loop as relay_loop

        relay_loop.start(workers[RELAY], stopping)
    if NEMO in workers:
        from bot.nemo import loop as nemo_loop

        nemo_loop.start(workers[NEMO], stopping)
        nemo_loop.start_missed_reaction_pass(workers[NEMO].client)


def start(name, app, token):
    handler = SocketModeHandler(app, token)
    thread = threading.Thread(target=handler.start, name=name, daemon=True)
    thread.start()
    log.info("%s connected", name)
    return handler


def main(argv=None):
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(name)s %(message)s",
    )
    load_dotenv(ENV_FILE)

    apps = parse_args(sys.argv[1:] if argv is None else argv).apps or list(APPS)

    missing = missing_variables(apps)
    if missing:
        print(
            f"bot: {', '.join(apps)} missing {len(missing)} variable(s): {', '.join(missing)}",
            file=sys.stderr,
        )
        print("Run `nemo doctor bot`", file=sys.stderr)
        return 78

    try:
        with session() as conn:
            refuse_if_seeded(conn)
    except SeededDeployment as refusal:
        print(f"bot: {refusal}", file=sys.stderr)
        shutdown()
        return 78

    built, workers = wire(apps)
    running = [start(name, app, token) for name, (app, token) in built.items()]
    stopping = threading.Event()

    start_loops(workers, stopping)

    def stop(*_):
        stopping.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    log.info("bot: up, %s", " and ".join(apps))
    with heartbeat_loop(worker(apps), lambda: app_list(apps)):
        stopping.wait()

    for handler in running:
        handler.close()
    shutdown()
    log.info("bot: stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
