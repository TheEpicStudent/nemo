import argparse
import copy
import pathlib
import re
import sys

import yaml
from dotenv import load_dotenv

from ingest import member_links as links
from lib.db import connect
from lib.paths import DB_DIR, ENV_FILE

VARIANT_NAME = re.compile(r"^[a-z0-9_]{1,40}$")
RESERVED_NAMES = ("live",)
VARIANTS_DIR = DB_DIR / "link_variants"


def overlay(base, changes):
    merged = copy.deepcopy(base)
    for key, value in (changes or {}).items():
        if value is None:
            merged.pop(key, None)
        elif isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = overlay(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def variant_path(value):
    if VARIANT_NAME.match(value):
        return VARIANTS_DIR / f"{value}.yml"
    return pathlib.Path(value)


def variant_name(path, name=None):
    chosen = name or pathlib.Path(path).stem
    if not VARIANT_NAME.match(chosen) or chosen in RESERVED_NAMES:
        raise ValueError(f"invalid variant name {chosen!r}")
    return chosen


def load_variant(path):
    changes = yaml.safe_load(pathlib.Path(path).read_text())
    if changes is not None and not isinstance(changes, dict):
        raise ValueError(f"{path} must be a YAML mapping")
    return overlay(links.catalogue(), changes)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="rebuild every link with a variant file applied to db/alt_signals.yml, into fd.member_link_shadow")
    parser.add_argument("--variant", required=True, metavar="FILE",
                        help="YAML whose keys replace those in db/alt_signals.yml, or the name of one in "
                             "db/link_variants; a null value removes the key")
    parser.add_argument("--name", help="variant name stored with the links; the file name without .yml by default")
    parser.add_argument("--dsn", help="Postgres DSN to use instead of the environment configuration")
    args = parser.parse_args(argv)
    load_dotenv(ENV_FILE)
    try:
        path = variant_path(args.variant)
        name = variant_name(path, args.name)
        config = load_variant(path)
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"links: {error}", file=sys.stderr)
        return 2
    with connect(args.dsn) as conn:
        written = links.build_shadow(conn, config, name)
    print(f"links: {written:,} link(s) written to fd.member_link_shadow as {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
