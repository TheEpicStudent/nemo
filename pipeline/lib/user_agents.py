import hashlib

from lib import useragent

UPSERT_SQL = """
INSERT INTO slack.user_agent (ua, app, os, read_at)
SELECT ua, app, os, now() FROM unnest(%s::text[], %s::text[], %s::text[]) AS incoming(ua, app, os)
ON CONFLICT (md5(ua)) DO NOTHING
"""

IDS_SQL = "SELECT md5(ua), id FROM slack.user_agent WHERE md5(ua) = ANY(%s)"


def digest(ua):
    return hashlib.md5(ua.encode()).hexdigest()


def ids(conn, agents):
    unique_agents = sorted({one for one in agents if one})
    if not unique_agents:
        return {}
    parsed = [useragent.parse(one) for one in unique_agents]
    conn.execute(UPSERT_SQL, (unique_agents, [one["ua_app"] for one in parsed], [one["ua_os"] for one in parsed]))
    return dict(conn.execute(IDS_SQL, ([digest(one) for one in unique_agents],)).fetchall())


def id_of(agents, ua):
    return agents.get(digest(ua)) if ua else None
