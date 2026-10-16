import argparse
import os
import sys
import time
from datetime import date, datetime, timezone

from dotenv import load_dotenv


import psycopg

from lib import calendar, sources
from lib.db import connect, credentials
from lib.paths import ENV_FILE
from lib.proxy_client import ProxyClient
from lib.settings import PERIOD
from lib.slack_client import bot_client

TOLERANCE = 0.01


def connect_reader():
    user, password = credentials("RAILS")
    return psycopg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
        dbname=os.environ["POSTGRES_DB"],
        user=user,
        password=password,
    )


STAMPS = ("updated_at", "created_at", "searched_at", "seen_at")


def columns_of(conn, table):
    schema, name = table.split(".", 1)
    with conn.cursor() as cur:
        cur.execute("""select column_name from information_schema.columns
                       where table_schema = %s and table_name = %s""", (schema, name))
        return {r[0] for r in cur.fetchall()}


def newest_stamp(conn, table, prefixes):
    schema, name = table.split(".", 1)
    table_columns = columns_of(conn, table)
    column = next((c for c in STAMPS if c in table_columns), None)
    if column is None:
        return None
    where, args = "", ()
    if "source" in table_columns and prefixes:
        where = " where source = any(%s)"
        args = (prefixes,)
    with conn.cursor() as cur:
        cur.execute(f"select max({column}) from {schema}.{name}{where}", args)
        return cur.fetchone()[0]


def source_prefixes(key):
    prefixes = []
    for name in sources.runs_as(key):
        head = name.split(":", 1)[0]
        if head not in prefixes:
            prefixes.append(head)
    return prefixes


def last_produced(conn, key):
    newest = None
    for table in sources.field_of(key, "writes"):
        if not table.startswith("raw.") or table.count(".") != 1:
            continue
        try:
            stamp = newest_stamp(conn, table, source_prefixes(key))
        except Exception:
            conn.rollback()
            continue
        if stamp and (newest is None or stamp > newest):
            newest = stamp
    return newest


def last_ok_run(conn, key):
    with conn.cursor() as cur:
        cur.execute("""select max(finished_at) from raw.ingest_run
                       where status = 'ok' and source = any(%s)""", (list(sources.runs_as(key)),))
        return cur.fetchone()[0]


def check_source_freshness(pipe_conn):
    now = datetime.now(timezone.utc)
    rows = []
    for key in sources.KEYS:
        cadence = sources.field_of(key, "cadence")
        window = PERIOD.get(cadence)
        if window is None:
            continue
        produced = last_produced(pipe_conn, key)
        last_ok_at = last_ok_run(pipe_conn, key)
        last_activity = max([x for x in (produced, last_ok_at) if x], default=None)
        allowed = window.total_seconds() / 3600
        if last_activity is None:
            rows.append((f"{key}, hours since it last produced", "fresh",
                         f"{cadence}, and nothing on record", None, allowed))
            continue
        age = (now - last_activity).total_seconds() / 3600
        rows.append((f"{key}, hours since it last produced", "fresh",
                     f"{cadence}, so {allowed:.0f}h", round(age, 1), allowed))
    return rows


FULL_PLAN_SQL = """
select max(x.finished_at) from (
    select p.id, p.finished_at, max(c.step_total) as planned
    from raw.ingest_run p
    join raw.ingest_run c on c.parent_run_id = p.id
    where p.source = 'nightly_sync'
    group by p.id, p.finished_at
) x where x.planned >= %s
"""

LAST_PLAN_SQL = """
select coalesce(max(c.step_total), 0)
from raw.ingest_run p
left join raw.ingest_run c on c.parent_run_id = p.id
where p.id = (select max(id) from raw.ingest_run
              where source = 'nightly_sync' and parent_run_id is null)
"""


HEARTBEAT_STALE_MINUTES = 15.0


def check_worker_heartbeat(pipe_conn):
    now = datetime.now(timezone.utc)
    with pipe_conn.cursor() as cur:
        cur.execute("select beat_at from raw.worker_heartbeat where worker = 'sync_worker'")
        row = cur.fetchone()
    if row is None:
        return [("minutes since the worker's last heartbeat", "fresh",
                 "no heartbeat on record, so the worker has not started since this shipped",
                 None, HEARTBEAT_STALE_MINUTES)]
    return [("minutes since the worker's last heartbeat", "fresh",
             f"{HEARTBEAT_STALE_MINUTES:.0f}, one heartbeat per poll",
             round((now - row[0]).total_seconds() / 60, 1), HEARTBEAT_STALE_MINUTES)]


def check_nightly_plan_complete(pipe_conn):
    total = len(sources.NIGHTLY_KEYS)
    now = datetime.now(timezone.utc)
    rows = []
    with pipe_conn.cursor() as cur:
        cur.execute(FULL_PLAN_SQL, (total,))
        newest = cur.fetchone()[0]
        cur.execute(LAST_PLAN_SQL)
        planned = cur.fetchone()[0]
    rows.append(("the last nightly, stages planned", "plan",
                 f"all {total} of them", planned, total))
    if newest is None:
        rows.append(("hours since a nightly ran every stage", "fresh",
                     "daily, and no full plan is on record", None, 20.0))
    else:
        rows.append(("hours since a nightly ran every stage", "fresh",
                     "daily, so 20h", round((now - newest).total_seconds() / 3600, 1), 20.0))
    return rows


def utc_date(value):
    if not value:
        return None
    return datetime.fromtimestamp(int(value), tz=timezone.utc).date()


def one(conn, sql, args=None):
    with conn.cursor() as cur:
        cur.execute(sql, args or ())
        row = cur.fetchone()
    return None if row is None else row[0]


def team_stats_today(client):
    end = one_date(client)
    resp = client.call(
        "team.stats.timeSeries",
        {"start_date": end.isoformat(), "end_date": end.isoformat()},
    )
    rows = resp.get("stats") or resp.get("data") or []
    return rows[-1] if rows else {}


def one_date(client):
    avail = calendar.available_iso(client, "member")
    return date.fromisoformat(avail["end_date"])


def member_page(client, count=500):
    avail = calendar.available_iso(client, "member")
    resp = client.call(
        "admin.analytics.getMemberAnalytics",
        {
            "start_date": avail["start_date"],
            "end_date": avail["end_date"],
            "sort_column": "messages_posted",
            "sort_direction": "desc",
            "count": count,
        },
    )
    return resp.get("member_activity") or [], resp.get("num_found")


def channel_page(client, count=500):
    end = one_date(client)
    resp = client.call(
        "admin.analytics.getChannelAnalytics",
        {
            "start_date": end.isoformat(),
            "end_date": end.isoformat(),
            "privacy": "public",
            "sort_column": "messages_count",
            "sort_direction": "desc",
            "count": count,
        },
    )
    return resp.get("channel_analytics") or [], resp.get("num_found")


def check_members_against_slack(conn, client):
    local_value = one(conn, "select total_members_count from analytics.mart_team_stats_daily "
                     "order by ds desc limit 1")
    stats = team_stats_today(client)
    reference_value = stats.get("total_members_count") or stats.get("total_members")
    return "mart_team_stats_daily.total_members_count", "slack", "team.stats.timeSeries", local_value, reference_value


def check_members_against_the_dimension(conn, client):
    local_value = one(conn, "select total_members_count from analytics.mart_team_stats_daily "
                     "order by ds desc limit 1")
    reference_value = one(conn, "select count(*) from analytics.dim_member where is_live")
    return "mart_team_stats_daily.total_members_count", "cross", "dim_member.is_live", local_value, reference_value


def check_account_type_totals(conn, client):
    local_value = one(conn, "select sum(invited) from analytics.mart_account_type")
    reference_value = one(conn, "select count(*) from analytics.dim_member "
                       "where not is_bot and not is_deleted")
    return "mart_account_type.invited, summed", "cross", "dim_member, live and not a bot", local_value, reference_value


def check_growth_cohorts(conn, client):
    local_value = one(conn, "select sum(invited_members) from analytics.mart_growth")
    reference_value = one(conn, """
        select count(*) from analytics.dim_member
        where cohort_at >= (select min(month) from analytics.mart_growth)
          and cohort_at <  (select max(month) + interval '1 month' from analytics.mart_growth)
          and not is_bot""")
    return "mart_growth.invited_members, summed", "cross", "dim_member.cohort_at", local_value, reference_value


def check_monthly_rollup(conn, client):
    local_value = one(conn, """
        select channel_messages from analytics.mart_team_stats_monthly
        where is_complete order by month desc limit 1""")
    reference_value = one(conn, """
        select sum(d.channel_messages_1d) from analytics.mart_team_stats_daily d
        where date_trunc('month', d.ds) = (
            select month from analytics.mart_team_stats_monthly
            where is_complete order by month desc limit 1)""")
    return "mart_team_stats_monthly.channel_messages", "cross", "the daily mart, summed", local_value, reference_value


def check_channel_source_parity(conn, client):
    lag = one(conn, """
        select greatest(0,
            (select max(window_end) from analytics.mart_channel_range)
          - (select max(window_start) from analytics.mart_channel_activity))""")
    return ("channel daily pull, days behind the walk", "cross",
            "up to 2, since the export lags the walk by a day", lag, 2)


def check_channel_members_against_slack(conn, client):
    rows, _ = channel_page(client, count=200)
    if not rows:
        return "mart_channel_range.total_members", "slack", "getChannelAnalytics", None, None
    top = rows[0]
    local_value = one(conn, "select total_members from analytics.mart_channel_range where channel_id = %s",
               (top["channel_id"],))
    return (f"mart_channel_range.total_members #{top.get('name')}", "slack",
            "getChannelAnalytics", local_value, top.get("total_members_count"))


def check_dimension_join_coverage(conn, client):
    fct_count = one(conn, "select count(*) from analytics.fct_channel_range")
    mart_count = one(conn, "select count(*) from analytics.mart_channel_range")
    return ("channels the dimension join drops", "cross",
            "0, every walked channel should reach the mart", fct_count - mart_count, 0)


def check_archived_flags_against_slack(conn, client):
    bot = bot_client()
    team = os.environ.get("SLACK_TEAM_ID")
    slack_archived, cursor = {}, ""
    while True:
        page = bot.conversations_list(types="public_channel", limit=1000,
                                      cursor=cursor, exclude_archived=False, team_id=team)
        for channel in page["channels"]:
            slack_archived[channel["id"]] = bool(channel.get("is_archived"))
        cursor = (page.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            break
        time.sleep(1.2)
    with conn.cursor() as cur:
        cur.execute("select channel_id from analytics.dim_channel where not archived")
        local_live = [r[0] for r in cur.fetchall()]
    drifted = sum(1 for cid in local_live if slack_archived.get(cid) is True)
    unlisted = sum(1 for cid in local_live if cid not in slack_archived)
    return [
        ("channels marked live locally but archived in Slack", "slack",
         "0, the archived flag should follow Slack", drifted, 0),
        ("local channels absent from the workspace listing", "slack",
         "reported, not judged: likely other teams in the grid", unlisted, unlisted),
    ]


def check_channel_count_against_slack(conn, client):
    _, slack_count = channel_page(client, count=1)
    local_value = one(conn, "select count(*) from analytics.mart_channel_range")
    return "mart_channel_range, row count", "slack", "getChannelAnalytics num_found", local_value, slack_count


def check_top_poster_against_slack(conn, client):
    row = None
    with conn.cursor() as cur:
        cur.execute("""select window_start, window_end, messages_posted
                       from analytics.mart_top_posters where rank = 1
                       order by month desc limit 1""")
        row = cur.fetchone()
    if row is None:
        return "mart_top_posters.messages_posted", "slack", "getMemberAnalytics", None, None
    start, end, local_value = row
    resp = client.call("admin.analytics.getMemberAnalytics", {
        "start_date": start.isoformat(), "end_date": end.isoformat(),
        "sort_column": "messages_posted", "sort_direction": "desc", "count": 1})
    recs = resp.get("member_activity") or []
    reference_value = recs[0].get("messages_posted") if recs else None
    return (f"mart_top_posters, rank 1 for {start:%b %Y}", "slack",
            "getMemberAnalytics over the same month", local_value, reference_value)


def check_distribution_population(conn, client):
    local_value = one(conn, "select max(workspace_members) from analytics.mart_activity_distribution")
    reference_value = one(conn, "select count(*) from analytics.dim_member "
                       "where not is_bot and not invite_pending")
    return "mart_activity_distribution.workspace_members", "cross", "dim_member, walkable", local_value, reference_value


RETENTION_COVERAGE_SQL = """
select count(distinct first_post_on) as dates,
       count(distinct first_post_on) filter (where day_30_covered) as day_30,
       count(distinct first_post_on) filter (where day_90_covered) as day_90,
       count(distinct first_post_on) filter (where visits_knowable) as visits
from analytics.fct_member_retention
"""

MEMBER_DAYS_SQL = "select window_start from analytics.fct_member_activity group by 1 order by 1"

VISITS_NEED = 15


def longest_run(days):
    best = run = 0
    for i, day in enumerate(days):
        run = run + 1 if i and (day - days[i - 1]).days == 1 else 1
        best = max(best, run)
    return best


def check_retention_coverage(conn, client):
    with conn.cursor() as cur:
        cur.execute(RETENTION_COVERAGE_SQL)
        dates, day_30, day_90, visits = cur.fetchone()
        cur.execute(MEMBER_DAYS_SQL)
        days = [r[0] for r in cur.fetchall()]
    return [
        ("first-post dates with a day-30 observation", "cover",
         "one member-day inside the 8 days at +23..+30", day_30, dates),
        ("first-post dates with a day-90 observation", "cover",
         "one member-day inside the 8 days at +83..+90", day_90, dates),
        ("first-post dates where visits are knowable", "cover",
         f"{VISITS_NEED} consecutive member-days from the first post", visits, dates),
        ("longest unbroken run of member-days", "cover",
         f"{VISITS_NEED}, which is what the visit steps need", longest_run(days), VISITS_NEED),
    ]


def check_response_rate_totals(conn, client):
    local_value = one(conn, """
        select coalesce(sum(answered_by_member), 0)
        from analytics.mart_response_rate""")
    reference_value = one(conn, """
        select count(*)
        from analytics.fct_first_response r
        join analytics.dim_member d on d.user_id = r.newcomer_id
        where r.answered
          and d.cohort_at is not null
          and not coalesce(d.is_bot, false)
          and not coalesce(d.is_deleted, false)
          and not coalesce(d.invite_pending, false)
          and r.post_at <= d.cohort_at + interval '30 days'""")
    return ("mart_response_rate, first posts a member answered", "cross",
            "fct_first_response rows inside the newcomer window", local_value, reference_value)


def check_claimed_against_slack(conn, client):
    local_value = one(conn, "select total_claimed_count from analytics.mart_team_stats_daily "
                     "order by ds desc limit 1")
    stats = team_stats_today(client)
    reference_value = stats.get("total_claimed_count")
    return "mart_team_stats_daily.total_claimed_count", "slack", "team.stats.timeSeries", local_value, reference_value


def check_claimed_flag(conn, client):
    local_value = one(conn, """
        select round(100.0 * count(*) filter (where is_claimed) / nullif(count(*), 0))
        from analytics.dim_member where is_live""")
    reference_value = one(conn, """
        select round(100.0 * total_claimed_count / nullif(total_members_count, 0))
        from analytics.mart_team_stats_daily order by ds desc limit 1""")
    return "claim rate, percent", "cross", "team.stats claim rate", local_value, reference_value


SLACK_CHECKS = {
    "check_members_against_slack",
    "check_claimed_against_slack",
    "check_channel_members_against_slack",
    "check_channel_count_against_slack",
    "check_archived_flags_against_slack",
    "check_top_poster_against_slack",
}

PIPELINE_CHECKS = [
    check_source_freshness,
    check_nightly_plan_complete,
    check_worker_heartbeat,
]

CHECKS = [
    check_members_against_slack,
    check_claimed_against_slack,
    check_members_against_the_dimension,
    check_claimed_flag,
    check_account_type_totals,
    check_growth_cohorts,
    check_monthly_rollup,
    check_channel_source_parity,
    check_channel_members_against_slack,
    check_channel_count_against_slack,
    check_dimension_join_coverage,
    check_archived_flags_against_slack,
    check_top_poster_against_slack,
    check_distribution_population,
    check_response_rate_totals,
    check_retention_coverage,
]


KNOWN_DIFFERENCES = {
    "claim rate, percent": (
        0.30, "our denominator is the live members we have walked, which excludes a large "
              "pool of never-claimed deactivated accounts that Slack still counts"
    ),
    "mart_team_stats_daily.total_members_count": (
        0.10, "Slack counts everyone in the org today; dim_member holds the members we have walked"
    ),
}


def stale_verdict(age, allowed):
    if age is None:
        return "no record", None
    if age <= allowed:
        return "ok", None
    return "stale", (age - allowed) / allowed


AT_LEAST = "at least"
AT_MOST = "at most"

BOUNDS = {
    "longest unbroken run of member-days": AT_LEAST,
    "the last nightly, stages planned": AT_LEAST,
    "channel daily pull, days behind the walk": AT_MOST,
}


def bound_verdict(name, local_value, reference_value):
    if local_value is None or reference_value is None:
        return "no data", None
    local_value, reference_value = float(local_value), float(reference_value)
    within_bound = local_value >= reference_value if BOUNDS[name] == AT_LEAST else local_value <= reference_value
    delta = None if reference_value == 0 else (local_value - reference_value) / reference_value
    return ("ok" if within_bound else "differs"), delta


def verdict(name, local_value, reference_value, tolerance):
    if local_value is None or reference_value is None:
        return "no data", None
    local_value, reference_value = float(local_value), float(reference_value)
    if reference_value == 0:
        return ("ok" if local_value == 0 else "differs"), None
    delta = (local_value - reference_value) / reference_value
    if abs(delta) <= tolerance:
        return "ok", delta
    bound = KNOWN_DIFFERENCES.get(name)
    if bound and abs(delta) <= bound[0]:
        return "known", delta
    return "differs", delta


def collect(only=None, tolerance=TOLERANCE, cross_only=False):
    load_dotenv(ENV_FILE)
    client = None if cross_only else ProxyClient()
    results = []
    skipped = 0
    with connect() as pipe:
        for check in PIPELINE_CHECKS:
            if only and only not in check.__name__:
                continue
            try:
                results.extend(check(pipe))
            except Exception as exc:
                pipe.rollback()
                results.append((check.__name__, "error", str(exc).splitlines()[0][:70],
                                None, None, "error", None))

    with connect_reader() as conn:
        for check in CHECKS:
            if only and only not in check.__name__:
                continue
            if cross_only and check.__name__ in SLACK_CHECKS:
                skipped += 1
                continue
            try:
                outcome = check(conn, client)
            except Exception as exc:
                conn.rollback()
                results.append((check.__name__, "error", str(exc).splitlines()[0][:70],
                                None, None, "error", None))
                continue
            for name, kind, source, local_value, reference_value in (outcome if isinstance(outcome, list) else [outcome]):
                if name in BOUNDS:
                    state, delta = bound_verdict(name, local_value, reference_value)
                else:
                    state, delta = verdict(name, local_value, reference_value, tolerance)
                results.append((name, kind, source, local_value, reference_value, state, delta))

    graded = []
    for row in results:
        if len(row) == 5:
            name, kind, source, local_value, reference_value = row
            if name in BOUNDS:
                state, delta = bound_verdict(name, local_value, reference_value)
            elif kind in ("plan", "cover"):
                state, delta = verdict(name, local_value, reference_value, 0.0)
            else:
                state, delta = stale_verdict(local_value, reference_value)
            graded.append((name, kind, source, local_value, reference_value, state, delta))
        else:
            graded.append(row)
    return graded, skipped


STATUS_OF = {"ok": "pass", "known": "pass", "differs": "fail", "stale": "fail", "error": "fail",
             "no data": "warn", "no record": "warn"}

RECORD_SQL = """
INSERT INTO ingest.quality_result (run_id, subject, assertion, severity, status, observed, expected)
VALUES (%s, 'headline', %s, %s, %s, %s, %s)
"""


def format_value(value):
    if value is None:
        return None
    return f"{value:,.2f}" if isinstance(value, float) else str(value)


def record_verdicts(conn, run_id, results):
    with conn.cursor() as cur:
        for name, kind, source, local_value, reference_value, state, delta in results:
            status = STATUS_OF.get(state, "warn")
            severity = "info" if status == "pass" else ("error" if status == "fail" else "warn")
            observed = format_value(local_value) if delta is None else f"{format_value(local_value)} ({delta * 100:+.2f}%)"
            cur.execute(RECORD_SQL, (run_id, f"{kind}:{name}", severity, status, observed,
                                     f"{format_value(reference_value)} from {source}"))
    conn.commit()
    return len(results)


def run(only=None, tolerance=TOLERANCE, cross_only=False, record=False, run_id=None):
    results, skipped = collect(only, tolerance, cross_only)
    if record:
        with connect() as conn:
            record_verdicts(conn, run_id, results)

    width = max(len(r[0]) for r in results)
    print(f"{'headline':<{width}}  {'kind':<6}{'value':>14}{'reference':>16}{'delta':>9}  state")
    print("-" * (width + 52))
    failed_count = 0
    for name, kind, source, local_value, reference_value, state, delta in results:
        if state not in ("ok", "known"):
            failed_count += 1
        delta_text = "" if delta is None else f"{delta * 100:+.2f}%"
        value_text = (
            "n/a" if local_value is None
            else f"{local_value:,.1f}" if isinstance(local_value, float)
            else f"{int(local_value):,}"
        )
        reference_text = (
            "n/a" if reference_value is None
            else f"{reference_value:,.0f}" if isinstance(reference_value, float)
            else f"{int(reference_value):,}"
        )
        print(f"{name:<{width}}  {kind:<6}{value_text:>14}{reference_text:>16}{delta_text:>9}  {state}")
        if state != "ok":
            note = KNOWN_DIFFERENCES.get(name)
            print(f"{'':<{width}}  against {source}")
            if state == "known" and note:
                print(f"{'':<{width}}  known: {note[1]}")
    print()
    print(f"{len(results) - failed_count} of {len(results)} within {tolerance * 100:g}% "
          "(known differences included)")
    if skipped:
        print(f"{skipped} check(s) that need Slack were skipped")
    return failed_count


def main():
    parser = argparse.ArgumentParser(description="check every headline metric against a second source")
    parser.add_argument("--only", help="substring of a check name")
    parser.add_argument("--tolerance", type=float, default=TOLERANCE)
    parser.add_argument("--cross-only", action="store_true",
                        help="skip the checks that call Slack, for a machine without credentials")
    parser.add_argument("--record", action="store_true",
                        help="write every verdict to ingest.quality_result")
    args = parser.parse_args()
    sys.exit(1 if run(args.only, args.tolerance, args.cross_only, args.record) else 0)


if __name__ == "__main__":
    main()
