import re
import time

from slack_sdk.errors import SlackApiError

SHROUD_BOT_USER_ID = "U07K4TS9HQE"
SHROUD_BOT_ID = "B07KBDVFXJP"

NAMED = "named"
ANONYMOUS = "anonymous"
UNKNOWN = "unknown"

AUTO = "auto"
PROMPT = "prompt"
SHORTCUT = "shortcut"

PACE_SECONDS = 1.2
PAGE = 200

SHORTCUT_HEAD = re.compile(r"^(?::triangular_flag_on_post:|\U0001F6A9) New report on a message")
REPORTED_BY = re.compile(r"Reported by <@([UW][A-Z0-9]+)>")
UNREADABLE = ("channel_not_found", "not_in_channel", "missing_scope", "access_denied", "is_archived")


def kind_of(auto_forward, selection_ts):
    if auto_forward:
        return AUTO
    return PROMPT if selection_ts else SHORTCUT


def shortcut_reporter(text):
    lines = (text or "").split("\n")
    if not SHORTCUT_HEAD.match(lines[0]) or len(lines) < 2:
        return None
    match = REPORTED_BY.fullmatch(lines[1].strip())
    return match.group(1) if match else None


def forward_choice(kind, message):
    if not message:
        return UNKNOWN, None
    if kind == SHORTCUT:
        reporter = shortcut_reporter(message.get("text"))
        return (NAMED, reporter) if reporter else (ANONYMOUS, None)
    payload = (message.get("metadata") or {}).get("event_payload") or {}
    if payload.get("source_user_id"):
        return NAMED, payload["source_user_id"]
    if kind == AUTO or message.get("username"):
        return NAMED, None
    return ANONYMOUS, None


def human_author(message):
    if not message or message.get("bot_id") or message.get("subtype"):
        return None
    return message.get("user")


def error_of(failure):
    return (failure.response or {}).get("error", "") if isinstance(failure, SlackApiError) else ""


class Messages:
    def __init__(self, clients, pace=PACE_SECONDS):
        self.clients = [client for client in clients if client is not None]
        self.pace = pace
        self.found = {}
        self.unreadable = set()

    def one(self, channel_id, ts):
        if (channel_id, ts) in self.found:
            return self.found[(channel_id, ts)]
        message = None
        for client in self.clients:
            try:
                response = client.conversations_history(channel=channel_id, oldest=ts, latest=ts,
                                                        inclusive=True, limit=1,
                                                        include_all_metadata=True)
            except SlackApiError as failure:
                if error_of(failure) in UNREADABLE:
                    continue
                raise
            finally:
                time.sleep(self.pace)
            message = next((one for one in response.get("messages") or [] if one.get("ts") == ts), None)
            self.found[(channel_id, ts)] = message
            return message
        self.unreadable.add(channel_id)
        return None

    def channel(self, channel_id, oldest, latest, wanted):
        for client in self.clients:
            try:
                self.page_through(client, channel_id, oldest, latest, wanted)
                return True
            except SlackApiError as failure:
                if error_of(failure) in UNREADABLE:
                    continue
                raise
        self.unreadable.add(channel_id)
        return False

    def page_through(self, client, channel_id, oldest, latest, wanted):
        cursor = None
        while True:
            response = client.conversations_history(channel=channel_id, oldest=oldest, latest=latest,
                                                    inclusive=True, limit=PAGE, cursor=cursor,
                                                    include_all_metadata=True)
            time.sleep(self.pace)
            for message in response.get("messages") or []:
                if message.get("ts") in wanted:
                    self.found[(channel_id, message["ts"])] = message
            cursor = ((response.get("response_metadata") or {}).get("next_cursor") or "").strip()
            if not cursor:
                return

    def known(self, channel_id, ts):
        return (channel_id, ts) in self.found

    def get(self, channel_id, ts):
        return self.found.get((channel_id, ts))


class Identity:
    def __init__(self, forwards, dms):
        self.forwards = forwards
        self.dms = dms
        self.dm_authors = {}

    def dm_author(self, dm_channel, dm_ts):
        if dm_channel in self.dm_authors:
            return self.dm_authors[dm_channel]
        author = human_author(self.dms.one(dm_channel, dm_ts)) if dm_channel and dm_ts else None
        if author:
            self.dm_authors[dm_channel] = author
        return author

    def decide(self, kind, forward, dm_channel, dm_ts, known_reporter=None):
        choice, reporter = forward_choice(kind, forward)
        if choice != NAMED:
            return choice, None
        if kind != SHORTCUT:
            reporter = reporter or known_reporter or self.dm_author(dm_channel, dm_ts)
        if not reporter:
            return UNKNOWN, None
        return NAMED, reporter
