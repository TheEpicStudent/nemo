import argparse
import os
import sys

from lib import shards, slack_connection

DATABASE = [
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
]

PIPELINE_ROLE = ["PIPELINE_DB_USER", "PIPELINE_DB_PASSWORD"]
DBT_ROLE = ["DBT_DB_USER", "DBT_DB_PASSWORD"]
RAILS_ROLE = ["RAILS_DB_USER", "RAILS_DB_PASSWORD"]

BOT_OPTIONAL = PIPELINE_ROLE + [
    "ANONYMOUS_ICON_URL",
    "APP_HOST",
    "EXEMPT_BOT_IDS",
    "INTAKE_FILE_MAX_BYTES",
    "LOG_LEVEL",
    "INTERNAL_PROXY_URL",
    "NEMO_JOIN_PACE_SECONDS",
    "NEMO_JOIN_PER_SWEEP",
    "NEMO_JOIN_SECONDS",
    "NEMO_SWEEP_SECONDS",
    "NEMO_DRY_RUN",
    "PROXY_TOKEN_NEMO",
    "RELAY_SWEEP_SECONDS",
    "SLACK_SOCKET_MODE",
    "SLACK_HTTP_HOST",
    "SLACK_HTTP_PORT",
    "TZ",
]

BOT_APPS = {"bot": ("relay", "nemo"), "bot.relay": ("relay",), "bot.nemo": ("nemo",)}

ROLES = {
    "serve": {
        "required": DATABASE + ["APP_HOST"],
        "optional": RAILS_ROLE + [
            "SECRET_KEY_BASE",
            "RAILS_MASTER_KEY",
            "HCA_ISSUER",
            "HCA_CLIENT_ID",
            "HCA_CLIENT_SECRET",
            "HCA_REDIRECT_URI",
            "NEMO_CLIENT_ID",
            "NEMO_CLIENT_SECRET",
            "SLACK_TEAM_ID",
            "FD_ENCRYPTION_PRIMARY_KEY",
            "FD_ENCRYPTION_DETERMINISTIC_KEY",
            "FD_ENCRYPTION_SALT",
            "INTERNAL_PROXY_URL",
            "PROMETHEUS_BASE_URL",
            "SLACKSCAN_URL",
            "SLACK_CHANNEL_MANAGER_ROLE_ID",
            "PROXY_TOKEN_WEB",
            "PROXY_ALLOW_PLAINTEXT",
            "RAILS_MAX_THREADS",
            "WEB_CONCURRENCY",
            "RAILS_LOG_LEVEL",
            "NEMO_STREAM",
            "TLS_DOMAIN",
            "BOOTSTRAP_ADMIN_SLACK_ID",
            "TZ",
        ],
    },
    "sync": {
        "required": DATABASE + ["INTERNAL_PROXY_URL", "INTERNAL_PROXY_TOKEN"],
        "optional": PIPELINE_ROLE + DBT_ROLE + [
            "PROMETHEUS_BASE_URL",
            "NEMO_BOT_TOKEN",
            "SLACK_TEAM_ID",
            "NIGHTLY_AT",
            "NIGHTLY_RUN_AT_START",
            "SYNC_POLL_SECONDS",
            "NEMO_BUILD_WAIT_SECONDS",
            "PROXY_ALLOW_PLAINTEXT",
            "MEMBER_HISTORY_LIMIT",
            "FIRST_REPLY_LIMIT",
            "TZ",
        ],
    },
    "history": {
        "required": DATABASE + ["INTERNAL_PROXY_URL", "INTERNAL_PROXY_TOKEN", "SLACK_TEAM_ID"],
        "optional": PIPELINE_ROLE + [
            "MEMBER_HISTORY_POLL_SECONDS",
            "PROXY_ALLOW_PLAINTEXT",
            "TZ",
        ],
    },
    "archive": {
        "required": DATABASE + ["INTERNAL_PROXY_URL", "INTERNAL_PROXY_TOKEN"],
        "optional": PIPELINE_ROLE + [
            "ARCHIVE_POLL_SECONDS",
            "ARCHIVE_EVENT_POLL_SECONDS",
            "ARCHIVE_HISTORY_BATCH",
            "ARCHIVE_REPLIES_BUDGET",
            "CHANNEL_TAIL_LOOKBACK_DAYS",
            "PROXY_ALLOW_PLAINTEXT",
            "SLACK_TEAM_ID",
            "TZ",
        ],
    },
    "audit": {
        "required": DATABASE + ["INTERNAL_PROXY_URL", "INTERNAL_PROXY_TOKEN"],
        "optional": PIPELINE_ROLE + [
            "AUDIT_ACCESS_BACKFILL",
            "AUDIT_ACCESS_BACKFILL_SECONDS",
            "AUDIT_NETWORK_SECONDS",
            "IPINFO_TOKEN",
            "AUDIT_ACCESS_SECONDS",
            "AUDIT_BACKFILL",
            "AUDIT_BACKFILL_SECONDS",
            "AUDIT_BACKFILL_SETS",
            "AUDIT_HORIZON_DAYS",
            "AUDIT_AGENT_SECONDS",
            "AUDIT_LINK_LIVE_SECONDS",
            "AUDIT_CLUSTER_SECONDS",
            "AUDIT_NEMO_ID",
            "AUDIT_TAIL_ACTIONS",
            "AUDIT_TAIL_SECONDS",
            "PROXY_ALLOW_PLAINTEXT",
            "TZ",
        ],
    },
    "transform": {
        "required": DATABASE,
        "optional": DBT_ROLE + ["TZ"],
    },
    "seed": {
        "required": DATABASE,
        "optional": PIPELINE_ROLE + DBT_ROLE + [
            "SEED_ALLOW_DB",
            "SEED_SCALE",
            "SEED_RNG",
            "SEED_HISTORY_MONTHS",
            "SEED_HOSTILE",
            "TZ",
        ],
    },
    "bot": {
        "required": DATABASE + [
            "RELAY_BOT_TOKEN",
            "NEMO_BOT_TOKEN",
            "SLACK_TEAM_ID",
        ],
        "optional": BOT_OPTIONAL + [
            "RELAY_APP_TOKEN",
            "RELAY_SIGNING_SECRET",
            "NEMO_APP_TOKEN",
            "NEMO_SIGNING_SECRET",
            "SHROUD_DATABASE_URL",
            "LYLA_DATABASE_URL",
            "FIREHOSE_DATABASE_URL",
        ],
    },
    "bot.relay": {
        "required": DATABASE + ["RELAY_BOT_TOKEN"],
        "optional": BOT_OPTIONAL + [
            "RELAY_APP_TOKEN",
            "RELAY_SIGNING_SECRET",
            "NEMO_BOT_TOKEN",
            "NEMO_APP_TOKEN",
            "NEMO_SIGNING_SECRET",
            "SLACK_TEAM_ID",
            "SHROUD_DATABASE_URL",
        ],
    },
    "bot.nemo": {
        "required": DATABASE + [
            "NEMO_BOT_TOKEN",
            "SLACK_TEAM_ID",
        ],
        "optional": BOT_OPTIONAL + [
            "NEMO_APP_TOKEN",
            "NEMO_SIGNING_SECRET",
            "RELAY_BOT_TOKEN",
            "RELAY_APP_TOKEN",
            "RELAY_SIGNING_SECRET",
            "LYLA_DATABASE_URL",
            "FIREHOSE_DATABASE_URL",
        ],
    },
    "provision": {
        "required": DATABASE,
        "optional": RAILS_ROLE + PIPELINE_ROLE + DBT_ROLE + [
            "BOOTSTRAP_ADMIN_SLACK_ID",
            "TZ",
        ],
    },
}

SECRETS = ("PASSWORD", "TOKEN", "SECRET", "KEY")

DEFAULTS = {
    "POSTGRES_PORT": "5432",
    "HCA_ISSUER": "https://auth.hackclub.com",
    "RAILS_MAX_THREADS": "5",
    "WEB_CONCURRENCY": "2",
    "RAILS_LOG_LEVEL": "info",
    "NEMO_STREAM": "1",
    "TZ": "UTC",
    "NIGHTLY_AT": "03:00",
    "NIGHTLY_RUN_AT_START": "false",
    "ARCHIVE_POLL_SECONDS": "300",
    "AUDIT_TAIL_SECONDS": "5",
    "AUDIT_BACKFILL_SECONDS": "120",
    "AUDIT_BACKFILL_SETS": "login_and_channel",
    "AUDIT_ACCESS_SECONDS": "3600",
    "AUDIT_ACCESS_BACKFILL": "off",
    "AUDIT_ACCESS_BACKFILL_SECONDS": "60",
    "AUDIT_NETWORK_SECONDS": "900",
    "AUDIT_HORIZON_DAYS": "90",
    "AUDIT_AGENT_SECONDS": "3600",
    "AUDIT_LINK_LIVE_SECONDS": "15",
    "AUDIT_CLUSTER_SECONDS": "3600",
    "SYNC_POLL_SECONDS": "60",
    "SEED_SCALE": "dev",
    "SEED_RNG": "1",
    "SEED_HISTORY_MONTHS": "16",
}

HEADINGS = {
    "serve": "web dashboard, public URL",
    "sync": "nightly sync worker, long running",
    "history": "member_history search backfill, long running",
    "transform": "dbt build, one shot",
    "seed": "synthetic data, transform, verify, one shot",
    "provision": "schemas, roles, grants and migrations, one shot",
    "bot": "relay and nemo, long running",
    "bot.relay": "relay only, long running",
    "bot.nemo": "nemo only, long running",
    "archive": "channel history and thread replies, long running",
    "audit": "Slack audit log tail and backfill, long running",
}

BOT_FORBIDDEN = [
    "SLACK_TOKEN",
    "SLACK_ADMIN_TOKEN",
    "INTERNAL_PROXY_TOKEN",
]

FORBIDDEN = {
    "serve": [
        "NEMO_BOT_TOKEN", "NEMO_APP_TOKEN", "NEMO_SIGNING_SECRET", "RELAY_SIGNING_SECRET",
        "SLACK_TOKEN", "SLACK_ADMIN_TOKEN", "INTERNAL_PROXY_TOKEN",
    ],
    "bot": BOT_FORBIDDEN,
    "bot.relay": BOT_FORBIDDEN,
    "bot.nemo": BOT_FORBIDDEN,
    "sync": ["SLACK_ADMIN_TOKEN"],
    "history": ["SLACK_ADMIN_TOKEN"],
    "archive": ["SLACK_ADMIN_TOKEN"],
}


def known(role):
    spec = ROLES[role]
    return spec["required"] + spec["optional"]


def required(role, env=None):
    apps = BOT_APPS.get(role, ())
    return ROLES[role]["required"] + slack_connection.credential_variables(apps, env)


def weak(role, env=None):
    return slack_connection.weak_signing_secrets(BOT_APPS.get(role, ()), env)


def missing(role, env=None):
    env = env if env is not None else os.environ
    return [name for name in required(role, env) if not env.get(name)]


def unexpected(role, env=None):
    env = env if env is not None else os.environ
    allowed = set(known(role))
    all_names = {name for spec in ROLES.values() for name in spec["required"] + spec["optional"]}
    return sorted(name for name in all_names - allowed if env.get(name))


def forbidden(role, env=None):
    env = env if env is not None else os.environ
    return [name for name in FORBIDDEN.get(role, []) if env.get(name)]


POOLS = {"archive": shards.PREFIX}


def report(role, env=None):
    missing_names = missing(role, env)
    extra = unexpected(role, env)
    forbidden_names = forbidden(role, env)
    weak_names = weak(role, env)

    print(f"role {role}")
    for name in required(role, env):
        state = "MISSING" if name in missing_names else "set"
        print(f"  required  {name:28} {state}")
    if extra:
        print("  unexpected:")
        for name in extra:
            print(f"    {name}")
    if role in POOLS:
        print(f"  pool      {shards.describe(env)}")
    if forbidden_names:
        print("  forbidden:")
        for name in forbidden_names:
            print(f"    {name}")
    if weak_names:
        print("  too short:")
        for name in weak_names:
            print(f"    {name}")
    if missing_names:
        print(f"{role}: {len(missing_names)} required variable(s) missing: {', '.join(missing_names)}")
    if forbidden_names:
        print(f"{role}: {len(forbidden_names)} forbidden variable(s) set")
    if weak_names:
        print(f"{role}: {len(weak_names)} signing secret(s) shorter than "
              f"{slack_connection.MIN_SIGNING_SECRET_LENGTH} characters")
    return 1 if missing_names or forbidden_names or weak_names else 0


def example(role):
    spec = ROLES[role]
    lines = [
        f"# {role}: {HEADINGS[role]}",
        "# generated by `make env-examples`, do not edit by hand",
        f"NEMO_ROLE={role}",
        "",
        "# required",
    ]
    for name in spec["required"]:
        lines.append(f"{name}={DEFAULTS.get(name, '')}")
    if spec["optional"]:
        lines += ["", "# optional"]
        for name in spec["optional"]:
            lines.append(f"{name}={DEFAULTS.get(name, '')}")
    return "\n".join(lines) + "\n"


def write_examples(directory):
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for role in sorted(ROLES):
        path = directory / f"{role}.env.example"
        path.write_text(example(role))
        written.append(path)
    return written


def main(argv=None):
    parser = argparse.ArgumentParser(prog="config")
    parser.add_argument("role", nargs="?", choices=sorted(ROLES))
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--no-env-file", action="store_true")
    args = parser.parse_args(argv)

    if args.write:
        from lib.paths import ENV_EXAMPLE_DIR

        for path in write_examples(ENV_EXAMPLE_DIR):
            print(f"wrote {path}")
        sys.exit(0)

    if not args.role:
        parser.error("a role is required unless --write is given")

    if not args.no_env_file:
        from dotenv import load_dotenv

        from lib.paths import ENV_FILE

        load_dotenv(ENV_FILE)
    sys.exit(report(args.role))


if __name__ == "__main__":
    main()
