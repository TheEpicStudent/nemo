import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from bot.core import session, shutdown
from lib.paths import ENV_FILE
from lyla import check, source


def run_check():
    lyla = source.connect()
    with session() as conn:
        lines = check.report(conn, lyla)
    lyla.close()
    for line in lines:
        print(line)
    return 0


COMMANDS = {"check": run_check}


def main(argv=None):
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(name)s %(message)s")
    load_dotenv(ENV_FILE)
    parser = argparse.ArgumentParser(prog="nemo lyla")
    parser.add_argument("command", choices=sorted(COMMANDS))
    args = parser.parse_args(argv)
    if not os.environ.get(source.URL):
        print(f"lyla: {source.URL} is not set", file=sys.stderr)
        return 78
    try:
        return COMMANDS[args.command]()
    finally:
        shutdown()


if __name__ == "__main__":
    sys.exit(main())
