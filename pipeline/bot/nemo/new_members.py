import logging

log = logging.getLogger("bot.nemo")

MEMBER = """
INSERT INTO fd.member (user_id, handle, display_name, avatar_url, avatar_hash,
                       tz, tz_offset, is_bot, is_deleted, is_admin, is_owner, is_org_admin,
                       is_org_owner, is_restricted, is_ultra_restricted, profile_updated_at,
                       synced_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, to_timestamp(%s), now())
ON CONFLICT (user_id) DO UPDATE SET
    handle = coalesce(EXCLUDED.handle, fd.member.handle),
    display_name = coalesce(EXCLUDED.display_name, fd.member.display_name),
    avatar_url = coalesce(EXCLUDED.avatar_url, fd.member.avatar_url),
    avatar_hash = coalesce(EXCLUDED.avatar_hash, fd.member.avatar_hash),
    tz = coalesce(EXCLUDED.tz, fd.member.tz),
    tz_offset = coalesce(EXCLUDED.tz_offset, fd.member.tz_offset),
    is_bot = EXCLUDED.is_bot,
    is_deleted = EXCLUDED.is_deleted,
    is_admin = EXCLUDED.is_admin,
    is_owner = EXCLUDED.is_owner,
    is_org_admin = EXCLUDED.is_org_admin,
    is_org_owner = EXCLUDED.is_org_owner,
    is_restricted = EXCLUDED.is_restricted,
    is_ultra_restricted = EXCLUDED.is_ultra_restricted,
    profile_updated_at = coalesce(EXCLUDED.profile_updated_at, fd.member.profile_updated_at),
    synced_at = now()
WHERE (fd.member.handle, fd.member.display_name, fd.member.avatar_url, fd.member.avatar_hash,
       fd.member.tz, fd.member.tz_offset, fd.member.is_bot, fd.member.is_deleted,
       fd.member.is_admin, fd.member.is_owner, fd.member.is_org_admin, fd.member.is_org_owner,
       fd.member.is_restricted, fd.member.is_ultra_restricted, fd.member.profile_updated_at)
      IS DISTINCT FROM (coalesce(EXCLUDED.handle, fd.member.handle),
                        coalesce(EXCLUDED.display_name, fd.member.display_name),
                        coalesce(EXCLUDED.avatar_url, fd.member.avatar_url),
                        coalesce(EXCLUDED.avatar_hash, fd.member.avatar_hash),
                        coalesce(EXCLUDED.tz, fd.member.tz),
                        coalesce(EXCLUDED.tz_offset, fd.member.tz_offset),
                        EXCLUDED.is_bot, EXCLUDED.is_deleted,
                        EXCLUDED.is_admin, EXCLUDED.is_owner,
                        EXCLUDED.is_org_admin, EXCLUDED.is_org_owner,
                        EXCLUDED.is_restricted, EXCLUDED.is_ultra_restricted,
                        coalesce(EXCLUDED.profile_updated_at, fd.member.profile_updated_at))
"""

IDENTITY = """
INSERT INTO fd.member_identity (user_id, real_name, first_name, last_name, email, updated_at)
VALUES (%s, %s, %s, %s, %s, now())
ON CONFLICT (user_id) DO UPDATE SET
    real_name = coalesce(EXCLUDED.real_name, fd.member_identity.real_name),
    first_name = coalesce(EXCLUDED.first_name, fd.member_identity.first_name),
    last_name = coalesce(EXCLUDED.last_name, fd.member_identity.last_name),
    email = coalesce(EXCLUDED.email, fd.member_identity.email),
    updated_at = now()
WHERE fd.member_identity.purged_at IS NULL
  AND (fd.member_identity.real_name, fd.member_identity.first_name,
       fd.member_identity.last_name, fd.member_identity.email)
      IS DISTINCT FROM (coalesce(EXCLUDED.real_name, fd.member_identity.real_name),
                        coalesce(EXCLUDED.first_name, fd.member_identity.first_name),
                        coalesce(EXCLUDED.last_name, fd.member_identity.last_name),
                        coalesce(EXCLUDED.email, fd.member_identity.email))
"""

JOINED = """
INSERT INTO fd.member_joins (user_id, joined_at, source)
VALUES (%s, now(), 'team_join')
ON CONFLICT (user_id) DO NOTHING
RETURNING user_id
"""


def normalized(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def valid_user(user):
    if not isinstance(user, dict):
        return None
    return user if user.get("id") else None


def member_row(user):
    profile = user.get("profile") or {}
    org = user.get("enterprise_user") or {}
    return (
        user["id"],
        normalized(user.get("name")),
        normalized(profile.get("display_name")) or normalized(profile.get("real_name")),
        normalized(profile.get("image_512")) or normalized(profile.get("image_192")),
        normalized(profile.get("avatar_hash")),
        normalized(user.get("tz")),
        user.get("tz_offset"),
        bool(user.get("is_bot")),
        bool(user.get("deleted")),
        bool(user.get("is_admin")),
        bool(user.get("is_owner")),
        bool(org.get("is_admin")),
        bool(org.get("is_owner")),
        bool(user.get("is_restricted")),
        bool(user.get("is_ultra_restricted")),
        user.get("updated"),
    )


def identity_row(user):
    profile = user.get("profile") or {}
    return (
        user["id"],
        normalized(profile.get("real_name")),
        normalized(profile.get("first_name")),
        normalized(profile.get("last_name")),
        normalized(profile.get("email")),
    )


def upsert_member(conn, user):
    conn.execute(MEMBER, member_row(user))
    conn.execute(IDENTITY, identity_row(user))
    return user["id"]


def arrived(conn, user):
    inserted = conn.execute(JOINED, (user["id"],)).fetchone()
    upsert_member(conn, user)
    return bool(inserted)
