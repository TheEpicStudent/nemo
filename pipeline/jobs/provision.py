import argparse
import os
import subprocess
import sys

from dotenv import load_dotenv
from psycopg import sql

from checks import roles
from jobs.migrate import main as apply_migrations
from lib import capabilities
from lib.db import connect_admin
from lib.paths import ENV_FILE, INIT_SQL, REPO_ROOT

WEB_DIR = REPO_ROOT / "web"

ROLE_PASSWORDS = [
    ("PIPELINE_DB_USER", "PIPELINE_DB_PASSWORD"),
    ("DBT_DB_USER", "DBT_DB_PASSWORD"),
    ("RAILS_DB_USER", "RAILS_DB_PASSWORD"),
]


def ensure_database():
    target = os.environ["POSTGRES_DB"]
    with connect_admin(maintenance=True) as conn:
        conn.autocommit = True
        if conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (target,)
        ).fetchone():
            return
        try:
            conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
        except Exception as exc:
            print(f"provision: could not create {target}: {exc}")
            raise SystemExit(1) from exc
    print(f"provision: created {target}")


def apply_init_sql(conn):
    notices = []
    conn.add_notice_handler(lambda note: notices.append(note.message_primary))
    conn.execute(INIT_SQL.read_text())
    conn.commit()
    for note in notices:
        if "already exists" not in note:
            print(f"provision: {note}")


def report_mode(conn):
    present_roles = roles.roles_present(conn)
    if len(present_roles) == len(roles.EXPECTED_ROLES):
        print(f"provision: {roles.SEPARATED_MODE} deployment, grants enforced by "
              f"{', '.join(present_roles)}")
        return
    print(f"provision: {roles.SHARED_MODE} deployment, services share "
          f"{os.environ.get('POSTGRES_USER', 'one login')}")


def set_role_passwords(conn):
    applied = []
    for user_var, password_var in ROLE_PASSWORDS:
        role = os.environ.get(user_var)
        password = os.environ.get(password_var)
        if not role or not password:
            continue
        if not conn.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone():
            continue
        conn.execute(
            sql.SQL("ALTER ROLE {} PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)
            )
        )
        applied.append(role)
    conn.commit()
    if applied:
        print(f"provision: set passwords for {', '.join(applied)}")
    else:
        print("provision: no role passwords to set")


def rails(*args):
    proc = subprocess.run(["./bin/rails", *args], cwd=WEB_DIR)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)


def apply_app_schema():
    rails(
        "runner",
        "ActiveRecord::Base.connection_pool.migration_context.migrate",
    )


def seed_staff():
    if not os.environ.get("BOOTSTRAP_ADMIN_SLACK_ID"):
        print("provision: BOOTSTRAP_ADMIN_SLACK_ID not set, skipping staff row")
        return
    rails("db:seed")


def main():
    parser = argparse.ArgumentParser(prog="provision")
    parser.add_argument("--create", action="store_true")
    args = parser.parse_args()

    load_dotenv(ENV_FILE)
    if args.create:
        ensure_database()

    print("provision: schemas, roles and grants")
    with connect_admin() as conn:
        apply_init_sql(conn)
        set_role_passwords(conn)
        report_mode(conn)

    print("provision: raw schema")
    apply_migrations("pre")

    print("provision: app schema")
    apply_app_schema()

    print("provision: post migrations")
    apply_migrations("post")

    print("provision: grants")
    with connect_admin() as conn:
        apply_init_sql(conn)

    print("provision: capabilities")
    with connect_admin() as conn:
        keys, pairs = capabilities.sync(conn)
        conn.commit()
    print(f"provision: {keys} capabilities, {pairs} role capability entries")

    print("provision: staff row")
    seed_staff()

    print("provision: done, run `nemo transform` next")


if __name__ == "__main__":
    sys.exit(main())
