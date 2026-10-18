import logging
import time

from psycopg.errors import LockNotAvailable

from bot.core import privileged, session
from bot.nemo import new_members, screening
from bot.nemo.surface import on_event
from ingest import member_links_live

log = logging.getLogger("bot.nemo")

LOCK_RETRY_DELAYS_SECONDS = (0.5, 2.0, 5.0)


@on_event("team_join", open_to_all=True)
def record_team_join(ctx):
    user = new_members.valid_user((ctx.payload or {}).get("user"))
    if user is None:
        return None

    with session() as conn:
        is_new = new_members.record_join(conn, user)

    log.info("nemo: %s joined the workspace%s", user["id"], "" if is_new else ", already known")
    if not is_new:
        return user["id"]

    full_profile = privileged.profile(user["id"]) or user
    email = ((full_profile.get("profile") or {}).get("email"))
    with session() as conn:
        if full_profile is not user:
            new_members.upsert_member(conn, full_profile)
        screening.screen(conn, user["id"], email, client=ctx.client)
    score_links(user["id"])
    return user["id"]


def score_links(user_id):
    try:
        with session() as conn:
            changed = member_links_live.score(conn, [user_id])
    except Exception as failure:  # noqa: BLE001
        log.warning("nemo: could not score links for %s, the live lane will: %s", user_id, failure)
        return None
    if changed is None:
        log.info("nemo: links for %s wait for the live lane to measure signal totals", user_id)
    return changed


@on_event("user_change", open_to_all=True)
def record_user_change(ctx):
    user = new_members.valid_user((ctx.payload or {}).get("user"))
    if user is None:
        return None

    upsert_with_retry(user)
    return user["id"]


def upsert_with_retry(user):
    for delay in (*LOCK_RETRY_DELAYS_SECONDS, None):
        try:
            with session() as conn:
                return new_members.upsert_member(conn, user)
        except LockNotAvailable:
            if delay is None:
                raise
            time.sleep(delay)
