import logging

from bot.core import access, session, whoami
from bot.nemo import case_actions, channel, channels
from bot.nemo.surface import reaction_watch

log = logging.getLogger("bot.nemo")

ROOT = "root"
CARD = "card"

OPEN_CASE_MESSAGES = """
SELECT c.id, 'root', c.card_channel_id, c.card_thread_ts FROM fd.cases c
WHERE c.resolved_at IS NULL AND c.card_channel_id IS NOT NULL AND c.card_thread_ts IS NOT NULL
UNION ALL
SELECT c.id, 'card', c.card_channel_id, c.card_ts FROM fd.cases c
WHERE c.resolved_at IS NULL AND c.card_channel_id IS NOT NULL AND c.card_ts IS NOT NULL
UNION ALL
SELECT r.case_id, 'card', r.card_channel_id, r.forwarded_ts FROM fd.case_reports r
JOIN fd.cases c ON c.id = r.case_id
WHERE c.resolved_at IS NULL AND r.card_channel_id IS NOT NULL AND r.forwarded_ts IS NOT NULL
ORDER BY 1, 2 DESC
"""


def close_reactions(client, channel_id, ts):
    response = client.reactions_get(channel=channel_id, timestamp=ts, full=True)
    reactions = ((response or {}).get("message") or {}).get("reactions") or []
    reaction_users = [(channel.reaction_base_name(one.get("name")), one.get("users") or []) for one in reactions]
    return [(name, user_ids) for name, user_ids in reaction_users if channel.is_close_reaction(name)]


def resolver_id(conn, case_id, message_kind, user_ids, bot_user_id):
    for user_id in user_ids:
        if user_id == bot_user_id:
            continue
        allowed, _reason = access.may(conn, user_id, "case.resolve", case_id if message_kind == CARD else None)
        if allowed:
            return user_id
    return None


def close_case(client, case_id, message_kind, reactions, bot_user_id):
    for reaction, user_ids in reactions:
        with session() as conn:
            user_id = resolver_id(conn, case_id, message_kind, user_ids, bot_user_id)
            if user_id is None:
                continue
            resolution = case_actions.close_without_notice(conn, case_id, reaction_watch.resolution_for(reaction), user_id)
        if resolution is not None:
            reaction_watch.after_resolve(client, case_id, resolution, user_id)
            log.info("nemo: case %s closed as %s from a %s reaction by %s made while stopped",
                     case_id, resolution, message_kind, user_id)
        return True
    return False


def apply_missed_close_reactions(client):
    bot_user_id = whoami.bot_user_id(client, "nemo")
    with session() as conn:
        messages = conn.execute(OPEN_CASE_MESSAGES).fetchall()
        react_channel_ids = channels.react_channels(conn)

    closed_case_ids = []
    for case_id, message_kind, channel_id, ts in messages:
        if case_id in closed_case_ids:
            continue
        if message_kind == ROOT and channel_id not in react_channel_ids:
            continue
        try:
            reactions = close_reactions(client, channel_id, ts)
        except Exception as failure:
            log.warning("nemo: could not read the reactions on %s in %s: %s", ts, channel_id, failure)
            continue
        if reactions and close_case(client, case_id, message_kind, reactions, bot_user_id):
            closed_case_ids.append(case_id)

    log.info("nemo: checked %s open case message(s) for missed close reactions, closed %s",
             len(messages), len(closed_case_ids))
    return closed_case_ids
