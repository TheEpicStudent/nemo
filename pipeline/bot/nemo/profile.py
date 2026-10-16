import logging

log = logging.getLogger("bot.nemo")

PROFILE_CACHE = {}

IMAGES = ("image_192", "image_72", "image_48", "image_512", "image_original")


def profile(client, user_id):
    if not user_id:
        return {"name": "unknown", "icon": None}
    if user_id in PROFILE_CACHE:
        return PROFILE_CACHE[user_id]

    member_profile = {"name": user_id, "icon": None}
    try:
        response = client.users_info(user=user_id)
        profile = response["user"].get("profile", {})
        member_profile["name"] = (
            profile.get("display_name")
            or response["user"].get("real_name")
            or user_id
        )
        member_profile["icon"] = next((profile[key] for key in IMAGES if profile.get(key)), None)
    except Exception as failure:
        log.warning("nemo: could not look up %s: %s", user_id, failure)

    PROFILE_CACHE[user_id] = member_profile
    return member_profile


def name(client, user_id):
    return profile(client, user_id)["name"]
