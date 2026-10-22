import itertools
import logging
import os
import threading
import time

from slack_sdk import WebClient
from slack_sdk.web.slack_response import SlackResponse

from lib import proxy_client

log = logging.getLogger("dry_run")

SETTING = "NEMO_DRY_RUN"
TRUTHY = frozenset({"1", "true", "yes", "on"})

READ_METHODS = frozenset({
    "apps.connections.open",
    "auth.test",
    "bots.info",
    "chat.getPermalink",
    "conversations.history",
    "conversations.info",
    "conversations.list",
    "conversations.members",
    "conversations.replies",
    "emoji.list",
    "files.info",
    "files.list",
    "reactions.get",
    "reactions.list",
    "search.messages",
    "team.info",
    "usergroups.list",
    "usergroups.users.list",
    "users.info",
    "users.list",
    "users.lookupByEmail",
    "users.profile.get",
    "admin.analytics.getChannelAnalytics",
    "admin.analytics.getAvailableDateRange",
    "admin.analytics.getFile",
    "admin.roles.listAssignments",
    "insights.messageStats",
})

held = []
_lock = threading.Lock()
_counter = itertools.count(1)
_installed = {}


def enabled(env=None):
    return (env if env is not None else os.environ).get(SETTING, "").strip().lower() in TRUTHY


def is_read(method):
    return method in READ_METHODS


def fake_ts():
    return f"{int(time.time())}.{next(_counter):06d}"


def hold(method, args):
    with _lock:
        held.append((method, args))
    log.warning("dry run: held %s %s", method, {key: args.get(key) for key in (
        "channel", "ts", "thread_ts", "name", "user", "users", "timestamp", "user_id") if key in args})
    channel = args.get("channel") or "DDRYRUN"
    return {"ok": True, "ts": fake_ts(), "channel": channel, "message": {"ts": fake_ts()},
            "file": {"id": "FDRYRUN"}, "files": [{"id": "FDRYRUN"}], "upload_url": None,
            "file_id": "FDRYRUN", "view": {"id": "VDRYRUN"}}


def install():
    if _installed:
        return False
    original_api_call = WebClient.api_call
    original_proxy_call = proxy_client.ProxyClient.call

    def api_call(self, api_method, **kwargs):
        if is_read(api_method):
            return original_api_call(self, api_method, **kwargs)
        args = dict(kwargs.get("json") or kwargs.get("data") or kwargs.get("params") or {})
        return SlackResponse(client=self, http_verb="POST", api_url=api_method, req_args=kwargs,
                             data=hold(api_method, args), headers={}, status_code=200)

    def proxy_call(self, method, params=None, max_retries=3, credential="internal"):
        if is_read(method):
            return original_proxy_call(self, method, params, max_retries, credential)
        return hold(method, dict(params or {}))

    WebClient.api_call = api_call
    proxy_client.ProxyClient.call = proxy_call
    _installed["api_call"] = original_api_call
    _installed["proxy_call"] = original_proxy_call
    log.warning("dry run: Slack writes are held, nothing is sent")
    return True


def uninstall():
    if not _installed:
        return False
    WebClient.api_call = _installed.pop("api_call")
    proxy_client.ProxyClient.call = _installed.pop("proxy_call")
    return True


def held_count():
    with _lock:
        return len(held)
