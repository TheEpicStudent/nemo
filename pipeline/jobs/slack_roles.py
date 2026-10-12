import argparse
import os
import sys
from collections import defaultdict

from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from lib.paths import ENV_FILE

PAGE_SIZE = 200
SAMPLES = 3
KINDS = {"C": "channel", "G": "private group", "T": "workspace", "E": "enterprise"}

BLOCKING = {
    "missing_scope",
    "not_allowed_token_type",
    "invalid_auth",
    "account_inactive",
    "token_revoked",
    "not_authed",
}


def exit_with_error(message):
    sys.exit(f"slack_roles: {message}")


def api(token):
    if not token:
        exit_with_error("no token. pass one as an argument or set SLACK_TOKEN to an xoxp user token")
    return WebClient(token=token)


def whoami(client):
    try:
        identity = client.auth_test().data
    except SlackApiError as exc:
        exit_with_error(f"auth.test failed: {exc.response.get('error', 'unknown_error')}")
    return identity


def call(client, **params):
    try:
        return client.admin_roles_listAssignments(limit=PAGE_SIZE, **params)
    except SlackApiError as exc:
        error = exc.response.get("error", "unknown_error")
        if error == "missing_scope":
            needed = exc.response.get("needed", "admin.roles:read")
            exit_with_error(f"the token is missing {needed}. add it and reinstall the app")
        if error in BLOCKING:
            exit_with_error(f"admin.roles.listAssignments refused this token: {error}")
        exit_with_error(f"admin.roles.listAssignments failed: {error}")


def walk(client, pages=None, **params):
    cursor = ""
    page_count = 0
    while True:
        page = call(client, cursor=cursor or None, **params)
        for one in page.get("role_assignments", []):
            yield one
        page_count += 1
        cursor = page.get("response_metadata", {}).get("next_cursor") or ""
        if not cursor or (pages is not None and page_count >= pages):
            return


def kind_of(entity_id):
    return KINDS.get(entity_id[:1], entity_id[:1] or "?")


def gather(client, pages):
    roles = defaultdict(lambda: {"count": 0, "entities": set(), "kinds": set(), "users": set()})
    for one in walk(client, pages=pages):
        entity = one.get("entity_id", "")
        role = roles[one.get("role_id", "?")]
        role["count"] += 1
        role["entities"].add(entity)
        role["kinds"].add(kind_of(entity))
        role["users"].add(one.get("user_id", ""))
    return roles


def report(roles, capped):
    print()
    print(f"  {'role_id':<10}{'assigned':>10}{'entities':>10}  {'kind':<14}samples")
    for role_id, one in sorted(roles.items(), key=lambda pair: -pair[1]["count"]):
        kinds = ", ".join(sorted(one["kinds"]))
        samples = ", ".join(sorted(one["entities"])[:SAMPLES])
        print(f"  {role_id:<10}{one['count']:>10}{len(one['entities']):>10}  {kinds:<14}{samples}")
    if capped:
        print(f"\n  counts cover the first {capped} pages only. pass --all to sweep everything.")


def channel_role(roles):
    candidates = [role for role, one in roles.items() if "channel" in one["kinds"]]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        print("\n  no role has channel entities. nothing here maps to channel manager.")
        return None
    print(f"\n  more than one role has channel entities: {', '.join(sorted(candidates))}")
    print("  pass --role to check one of them against a channel you know.")
    return None


def check_filter(client, role_id, channel_id):
    print(f"\n  filter check: role_ids={role_id} entity_ids={channel_id}")
    rows = list(walk(client, role_ids=[role_id], entity_ids=[channel_id]))
    if not rows:
        print("  nothing came back. the filter may not combine, or nobody manages that channel.")
        return
    unexpected = {row.get("entity_id") for row in rows} - {channel_id}
    users = sorted({row.get("user_id", "") for row in rows})
    print(f"  {len(rows)} assignments, {len(users)} people")
    print(f"  managers: {', '.join(users[:8])}{' ...' if len(users) > 8 else ''}")
    if unexpected:
        print(f"  WARNING entity_ids did not narrow it. also returned: {', '.join(sorted(unexpected)[:5])}")
    else:
        print("  every row is on that channel, so one call answers one channel")


def main():
    parser = argparse.ArgumentParser(
        prog="slack_roles",
        description="find which Slack role id means channel manager, and prove that "
                    "role_ids and entity_ids together answer one channel in one call",
    )
    parser.add_argument("token", nargs="?", help="an xoxp user token, else SLACK_TOKEN is used")
    parser.add_argument("--all", action="store_true", help="scan all pages instead of a sample")
    parser.add_argument("--pages", type=int, default=10, help="pages to sample, 200 per page")
    parser.add_argument("--role", help="skip discovery and check this role id")
    parser.add_argument("--channel", help="channel id for the filter check")
    args = parser.parse_args()

    load_dotenv(ENV_FILE)
    client = api(args.token or os.environ.get("SLACK_TOKEN", "").strip())
    identity = whoami(client)
    print(f"admin.roles.listAssignments as {identity.get('user')} ({identity.get('user_id')}) "
          f"on {identity.get('team')} / {identity.get('team_id')}")

    role_id = args.role
    channel_id = args.channel

    if role_id is None:
        pages = None if args.all else args.pages
        roles = gather(client, pages)
        if not roles:
            exit_with_error("no role assignments came back at all")
        report(roles, None if args.all else args.pages)
        role_id = channel_role(roles)
        if role_id is None:
            return
        if channel_id is None:
            channel_id = sorted(roles[role_id]["entities"])[0]
        print(f"\n  channel manager looks like {role_id}")
        print(f"  pin it:  SLACK_CHANNEL_MANAGER_ROLE_ID={role_id}")

    if channel_id is None:
        exit_with_error("pass --channel with --role so the filter can be checked")

    check_filter(client, role_id, channel_id)


if __name__ == "__main__":
    main()
