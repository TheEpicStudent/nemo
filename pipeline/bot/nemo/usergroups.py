import logging

from slack_sdk.errors import SlackApiError

from bot.core import session
from bot.nemo import channels

log = logging.getLogger("bot.nemo")

REFRESH_SECONDS = 3600

UPSERT = """
INSERT INTO fd.slack_usergroups (usergroup_id, handle, name, refreshed_at)
VALUES (%s, %s, %s, now())
ON CONFLICT (usergroup_id) DO UPDATE
SET handle = EXCLUDED.handle, name = EXCLUDED.name, refreshed_at = now()
"""


def fetch(client):
    params = {"include_disabled": True}
    team_id = channels.team()
    if team_id:
        params["team_id"] = team_id
    return (client.usergroups_list(**params) or {}).get("usergroups") or []


def rows_from(usergroups):
    return [(one["id"], one["handle"], one.get("name"))
            for one in usergroups if one.get("id") and one.get("handle")]


def refresh(client):
    try:
        rows = rows_from(fetch(client))
    except SlackApiError as failure:
        log.warning("nemo: could not list user groups: %s", failure.response.get("error"))
        return 0
    if not rows:
        return 0
    with session() as conn:
        with conn.cursor() as cursor:
            cursor.executemany(UPSERT, rows)
    log.info("nemo: stored %s user group handle(s)", len(rows))
    return len(rows)
