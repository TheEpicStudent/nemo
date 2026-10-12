import json
import logging
import threading
import urllib.error
import urllib.request
from urllib.parse import quote

log = logging.getLogger("bot.profiles")

HOST = "https://cachet.hackclub.com/users"
TIMEOUT = 5
UNKNOWN = "Unknown"

KNOWN = {}
LOCK = threading.Lock()


def icon_url(user_id):
    return f"{HOST}/{quote(user_id, safe='')}/r"


def fetch(user_id):
    request = urllib.request.Request(
        f"{HOST}/{quote(user_id, safe='')}", headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            body = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        log.warning("profiles: could not ask cachet about %s: %s", user_id, error)
        return None

    display = body.get("displayName")
    return display if display and display != UNKNOWN else None


def name(user_id):
    if not user_id:
        return None
    with LOCK:
        if user_id in KNOWN:
            return KNOWN[user_id]

    display_name = fetch(user_id)
    with LOCK:
        KNOWN[user_id] = display_name
    return display_name
