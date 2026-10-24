import argparse
import collections
import logging
import os
import re
import sys
import time

import psycopg
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from bot.core import session, shutdown
from bot.core.identity import ensure_member
from jobs import shroud_identity
from lib.paths import ENV_FILE
from lib.slack_client import RETRY_HANDLERS
from lyla import store
from lyla.mapping import LYLA_BOT_USER_ID

log = logging.getLogger("import_repair")

SHROUD_URL = "SHROUD_DATABASE_URL"
HEADER = re.compile("^Case #\u200c?([0-9]+)$")
HEADER_REPLIES = 20
CHAIN_HOPS = 10
SAMPLE = 8

IMPORTED_REPORTS = """
SELECT r.id, r.case_id, split_part(r.external_ref, ':', 3)::bigint, r.is_anonymous,
       r.reporter_user_id, r.card_channel_id, r.forwarded_ts, v.id,
       (SELECT m.author_user_id FROM fd.intake_messages m
         WHERE m.conversation_id = v.id AND m.direction = 'inbound' AND m.author_user_id IS NOT NULL
         ORDER BY m.posted_at, m.id LIMIT 1)
FROM fd.case_reports r
LEFT JOIN fd.intake_conversations v ON v.report_id = r.id
WHERE r.source_app = 'shroud' AND r.forwarded_ts IS NOT NULL AND r.card_channel_id IS NOT NULL
ORDER BY r.id
"""

SHROUD_ROWS = """
SELECT id, dm_channel, dm_ts, selection_ts, is_auto_forward FROM reports WHERE id = ANY(%s)
"""

NAME_REPORT = """
UPDATE fd.case_reports
SET is_anonymous = false, reporter_user_id = %(reporter)s, dm_channel_id = %(dm_channel)s,
    dm_ts = %(dm_ts)s
WHERE id = %(report_id)s AND is_anonymous
"""

NAME_CONVERSATION = """
UPDATE fd.intake_conversations
SET member_user_id = coalesce(member_user_id, %(reporter)s), consent_choice = 'named'
WHERE report_id = %(report_id)s
"""

NAME_MESSAGES = """
UPDATE fd.intake_messages
SET author_user_id = %(reporter)s, subtype = NULL
WHERE conversation_id = %(conversation_id)s AND direction = 'inbound'
  AND author_user_id IS NULL AND subtype = 'imported'
"""

HIDE_REPORT = """
UPDATE fd.case_reports
SET is_anonymous = true, reporter_user_id = NULL, dm_channel_id = NULL, dm_ts = NULL
WHERE id = %(report_id)s AND NOT is_anonymous
"""

HIDE_CONVERSATION = """
UPDATE fd.intake_conversations SET consent_choice = 'anonymous' WHERE report_id = %(report_id)s
"""

MERGED_REPORTS = """
SELECT r.id, r.case_id, r.card_channel_id, r.forwarded_ts
FROM fd.case_reports r
WHERE r.source_app = 'shroud' AND r.forwarded_ts IS NOT NULL AND r.card_channel_id IS NOT NULL
  AND EXISTS (SELECT 1 FROM fd.cases d WHERE d.duplicate_of = r.case_id)
ORDER BY r.id
"""

STORED_HEADERS = """
SELECT DISTINCT ON (channel_id, thread_ts) channel_id, thread_ts, body
FROM fd.case_chat
WHERE author_user_id = %s AND ts IS NOT NULL AND body LIKE 'Case #%%'
ORDER BY channel_id, thread_ts, posted_at, id
"""

PARENT = "SELECT duplicate_of FROM fd.cases WHERE id = %s"

MOVE_REPORT = "UPDATE fd.case_reports SET case_id = %s WHERE id = %s AND case_id = %s"

MIRROR_CONDITION = """
(EXISTS (SELECT 1 FROM fd.intake_messages m WHERE m.mirrored_ts = c.ts)
 OR EXISTS (SELECT 1 FROM fd.intake_outbox o WHERE o.echoed_ts = c.ts)
 OR EXISTS (SELECT 1 FROM fd.case_chat d WHERE d.mirrored_ts = c.ts AND d.id <> c.id))
"""

MIRROR_ROWS = f"""
SELECT c.id
FROM fd.case_chat c
JOIN fd.cases k ON k.id = c.case_id
WHERE k.source_app = 'lyla' AND c.ts IS NOT NULL AND {MIRROR_CONDITION}
ORDER BY c.id
"""

LYLA_ROWS = f"""
SELECT c.id
FROM fd.case_chat c
JOIN fd.cases k ON k.id = c.case_id
WHERE k.source_app = 'lyla' AND c.ts IS NOT NULL AND c.author_user_id = %s
  AND NOT {MIRROR_CONDITION}
ORDER BY c.id
"""

DELETE_CHAT = "DELETE FROM fd.case_chat WHERE id = ANY(%s)"


def sample(items):
    return sorted(items)[:SAMPLE]


def header_number(text):
    match = HEADER.match((text or "").strip())
    return int(match.group(1)) if match else None


class Threads:
    def __init__(self, clients, pace=shroud_identity.PACE_SECONDS):
        self.clients = [client for client in clients if client is not None]
        self.pace = pace

    def header(self, channel_id, thread_ts):
        for client in self.clients:
            try:
                response = client.conversations_replies(channel=channel_id, ts=thread_ts,
                                                        limit=HEADER_REPLIES)
            except SlackApiError as failure:
                if shroud_identity.error_of(failure) in shroud_identity.UNREADABLE:
                    continue
                raise
            finally:
                time.sleep(self.pace)
            for message in response.get("messages") or []:
                if message.get("user") == LYLA_BOT_USER_ID:
                    number = header_number(message.get("text"))
                    if number:
                        return number
            return None
        return None


def plan_identity(conn, shroud, identity):
    reports = conn.execute(IMPORTED_REPORTS).fetchall()
    rows = {row[0]: row for row in shroud.execute(SHROUD_ROWS, ([one[2] for one in reports],)).fetchall()}
    wanted = collections.defaultdict(set)
    for report in reports:
        wanted[report[5]].add(report[6])
    for channel_id, timestamps in wanted.items():
        identity.forwards.channel(channel_id, min(timestamps), max(timestamps), timestamps)

    plan = collections.defaultdict(list)
    for (report_id, case_id, shroud_id, anonymous, reporter, channel_id, forwarded_ts, conversation_id,
         known_author) in reports:
        row = rows.get(shroud_id)
        if row is None:
            plan["no_shroud_row"].append(report_id)
            continue
        _, dm_channel, dm_ts, selection_ts, auto_forward = row
        kind = shroud_identity.kind_of(auto_forward, selection_ts)
        if channel_id in identity.forwards.unreadable:
            plan["unreadable_channel"].append(report_id)
            continue
        forward = identity.forwards.get(channel_id, forwarded_ts)
        choice, found = identity.decide(kind, forward, dm_channel, dm_ts, reporter or known_author)
        entry = {"report_id": report_id, "case_id": case_id, "conversation_id": conversation_id,
                 "reporter": found, "dm_channel": dm_channel, "dm_ts": dm_ts, "kind": kind}
        if choice == shroud_identity.UNKNOWN:
            plan["missing_forward" if forward is None else "no_reporter_found"].append(report_id)
        elif choice == shroud_identity.NAMED and anonymous:
            plan["to_name"].append(entry)
        elif choice == shroud_identity.ANONYMOUS and not anonymous:
            plan["to_anonymize"].append(entry)
        elif choice == shroud_identity.NAMED and found != reporter:
            plan["reporter_differs"].append(report_id)
        else:
            plan["already_named" if choice == shroud_identity.NAMED else "already_anonymous"].append(report_id)
    return plan


def apply_identity(plan):
    done = collections.Counter()
    for entry in plan.get("to_name", []):
        with session() as conn:
            store.as_lyla(conn)
            ensure_member(conn, entry["reporter"])
            if conn.execute(NAME_REPORT, entry).rowcount:
                conn.execute(NAME_CONVERSATION, entry)
                if entry["conversation_id"]:
                    conn.execute(NAME_MESSAGES, entry)
                done["named"] += 1
    for entry in plan.get("to_anonymize", []):
        with session() as conn:
            store.as_lyla(conn)
            if conn.execute(HIDE_REPORT, entry).rowcount:
                conn.execute(HIDE_CONVERSATION, entry)
                done["anonymized"] += 1
    return done


def reaches(conn, start, goal):
    current = start
    for _ in range(CHAIN_HOPS):
        row = conn.execute(PARENT, (current,)).fetchone()
        if row is None or row[0] is None:
            return False
        if row[0] == goal:
            return True
        current = row[0]
    return False


def plan_reports(conn, threads):
    stored = {}
    for channel_id, thread_ts, body in conn.execute(STORED_HEADERS, (LYLA_BOT_USER_ID,)).fetchall():
        number = header_number(body)
        if number:
            stored[(channel_id, thread_ts)] = number
    plan = collections.defaultdict(list)
    for report_id, case_id, channel_id, forwarded_ts in conn.execute(MERGED_REPORTS).fetchall():
        number = stored.get((channel_id, forwarded_ts))
        if number is None:
            number = threads.header(channel_id, forwarded_ts)
        if number is None:
            plan["no_header"].append(report_id)
        elif number == case_id:
            plan["already_home"].append(report_id)
        elif reaches(conn, number, case_id):
            plan["to_move"].append({"report_id": report_id, "from": case_id, "to": number})
        else:
            plan["header_outside_family"].append(report_id)
    return plan


def apply_reports(plan):
    moved = 0
    for entry in plan.get("to_move", []):
        with session() as conn:
            store.as_lyla(conn)
            if conn.execute(MOVE_REPORT, (entry["to"], entry["report_id"], entry["from"])).rowcount:
                store.touch_case(conn, entry["from"])
                store.touch_case(conn, entry["to"])
                moved += 1
    return {"moved": moved}


def plan_chat(conn):
    mirrors = [row[0] for row in conn.execute(MIRROR_ROWS).fetchall()]
    lyla = [row[0] for row in conn.execute(LYLA_ROWS, (LYLA_BOT_USER_ID,)).fetchall()]
    return {"mirror_copies": mirrors, "lyla_messages": lyla}


def apply_chat(plan, batch=500):
    done = collections.Counter()
    for key in ("mirror_copies", "lyla_messages"):
        ids = plan.get(key, [])
        for start in range(0, len(ids), batch):
            with session() as conn:
                done[key] += conn.execute(DELETE_CHAT, (ids[start:start + batch],)).rowcount
    return done


def print_plan(step, plan):
    for key in sorted(plan):
        items = plan[key]
        ids = [item["report_id"] if isinstance(item, dict) else item for item in items]
        print(f"{step}: {key} {len(items)} {sample(ids)}")


def clients():
    relay = WebClient(token=os.environ["RELAY_BOT_TOKEN"], retry_handlers=RETRY_HANDLERS)
    nemo = (WebClient(token=os.environ["NEMO_BOT_TOKEN"], retry_handlers=RETRY_HANDLERS)
            if os.environ.get("NEMO_BOT_TOKEN") else None)
    return relay, nemo


def run_identity(apply):
    relay, nemo = clients()
    identity = shroud_identity.Identity(shroud_identity.Messages([relay, nemo]),
                                        shroud_identity.Messages([relay]))
    with psycopg.connect(os.environ[SHROUD_URL], options="-c default_transaction_read_only=on") as shroud:
        with session() as conn:
            plan = plan_identity(conn, shroud, identity)
    print_plan("identity", plan)
    return apply_identity(plan) if apply else {}


def run_reports(apply):
    relay, nemo = clients()
    with session() as conn:
        plan = plan_reports(conn, Threads([nemo, relay]))
    print_plan("reports", plan)
    return apply_reports(plan) if apply else {}


def run_chat(apply):
    with session() as conn:
        plan = plan_chat(conn)
    print_plan("chat", plan)
    return apply_chat(plan) if apply else {}


STEPS = {"identity": run_identity, "reports": run_reports, "chat": run_chat}
NEEDS = {"identity": ("RELAY_BOT_TOKEN", SHROUD_URL), "reports": ("RELAY_BOT_TOKEN",), "chat": ()}


def main(argv=None):
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper(),
                        format="%(asctime)s %(name)s %(message)s")
    load_dotenv(ENV_FILE)
    parser = argparse.ArgumentParser(prog="nemo import-repair")
    parser.add_argument("step", choices=sorted(STEPS))
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    missing = [name for name in NEEDS[args.step] if not os.environ.get(name)]
    if missing:
        print(f"import repair: {', '.join(missing)} not set", file=sys.stderr)
        return 78
    try:
        done = STEPS[args.step](args.apply)
    finally:
        shutdown()
    for key, count in sorted(done.items()):
        print(f"{args.step}: applied {key} {count}")
    if not args.apply:
        print(f"{args.step}: dry run, nothing written; add --apply to write")
    return 0


if __name__ == "__main__":
    sys.exit(main())
