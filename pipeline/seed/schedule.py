import collections
import math
from datetime import datetime, time, timedelta, timezone

from ingest.channel_history_pull import SOURCE
from lib.message import SUBSTANTIVE_CHARS

REPLY_SHARE = 0.18
MENTION_SHARE = 0.22
QUESTION_SHARE = 0.15
LINK_SHARE = 0.08
EMOJI_ONLY_SHARE = 0.06
BOT_SHARE = 0.03
FILE_SHARE = 0.05
EDITED_SHARE = 0.04

LENGTH_MU = math.log(21)
LENGTH_SIGMA = 1.1
LENGTH_CAP = 4000

ROOT_MEMORY = 40
REPLY_WINDOW_SECONDS = 48 * 3600

DAY_START_HOUR = 6
DAY_SPAN_SECONDS = 16 * 3600

MESSAGE_COLUMNS = [
    "channel_id", "ts", "source", "author_id", "author_kind", "subtype", "thread_root_ts",
    "is_reply", "posted_at", "edited_at", "edited_by", "reply_count", "reply_users_count",
    "latest_reply_ts", "reaction_count", "reactor_count", "file_count", "text_length",
    "mention_count", "is_question", "is_substantive", "has_link", "emoji_only",
    "mentioned_ids", "observed_at",
]

THREAD_COLUMNS = [
    "channel_id", "root_ts", "reply_count", "reply_users_count", "latest_reply_ts",
    "replies_fetched", "fetched_through_ts", "fetched_at", "seen_at",
]

WALK_COLUMNS = [
    "channel_id", "oldest_ts", "newest_ts", "messages_seen", "history_complete",
    "last_walked_at", "updated_at",
]


class Message:
    __slots__ = (
        "channel_id", "ts", "at", "author_id", "is_bot", "root_ts", "is_reply",
        "reactions", "repliers", "reply_count", "latest_reply_ts", "mentioned",
    )

    def __init__(self, channel_id, ts, at, author_id, is_bot, reactions):
        self.channel_id = channel_id
        self.ts = ts
        self.at = at
        self.author_id = author_id
        self.is_bot = is_bot
        self.reactions = reactions
        self.root_ts = None
        self.is_reply = False
        self.repliers = set()
        self.reply_count = 0
        self.latest_reply_ts = None
        self.mentioned = []


def stamp(at):
    return f"{at.timestamp():.6f}"


def day_seconds(rng):
    return DAY_START_HOUR * 3600 + rng.random() * DAY_SPAN_SECONDS


def spread(rng, day, count):
    base = datetime.combine(day, time(0, 0), tzinfo=timezone.utc)
    return sorted(base + timedelta(seconds=day_seconds(rng)) for _ in range(count))


def text_length(rng):
    return min(LENGTH_CAP, max(1, round(rng.lognormvariate(LENGTH_MU, LENGTH_SIGMA))))


def by_channel_day(events):
    events_by_channel = collections.defaultdict(list)
    for event in events:
        if event.messages > 0:
            events_by_channel[event.channel_id].append(event)
    return events_by_channel


def channel_messages(rng, channel_id, events, bots):
    messages = []
    for event in events:
        at_list = spread(rng, event.day, event.messages)
        share = event.reactions / event.messages if event.messages else 0
        for at in at_list:
            reactions = int(share) + (1 if rng.random() < share - int(share) else 0)
            messages.append(
                Message(channel_id, stamp(at), at, event.user_id,
                        event.user_id in bots, reactions)
            )
    messages.sort(key=lambda m: m.ts)
    return messages


def assign_threads(rng, messages):
    recent = collections.deque(maxlen=ROOT_MEMORY)
    for message in messages:
        candidates = [
            root for root in recent
            if root.author_id != message.author_id
            and (message.at - root.at).total_seconds() <= REPLY_WINDOW_SECONDS
        ]
        if candidates and rng.random() < REPLY_SHARE:
            root = candidates[-1]
            message.is_reply = True
            message.root_ts = root.ts
            root.repliers.add(message.author_id)
            root.reply_count += 1
            root.latest_reply_ts = message.ts
            root.root_ts = root.ts
            if rng.random() < MENTION_SHARE:
                message.mentioned = [root.author_id]
            continue
        recent.append(message)
        if candidates and rng.random() < MENTION_SHARE:
            message.mentioned = [candidates[-1].author_id]
    return messages


def message_row(rng, message, as_of):
    length = text_length(rng)
    edited = rng.random() < EDITED_SHARE
    return (
        message.channel_id,
        message.ts,
        SOURCE,
        message.author_id,
        "bot" if message.is_bot else "member",
        None,
        message.root_ts,
        message.is_reply,
        message.at,
        message.at + timedelta(minutes=2) if edited else None,
        message.author_id if edited else None,
        message.reply_count or None,
        len(message.repliers) or None,
        message.latest_reply_ts,
        message.reactions,
        message.reactions,
        1 if rng.random() < FILE_SHARE else 0,
        length,
        len(message.mentioned),
        rng.random() < QUESTION_SHARE,
        length >= SUBSTANTIVE_CHARS,
        rng.random() < LINK_SHARE,
        rng.random() < EMOJI_ONLY_SHARE,
        message.mentioned,
        as_of,
    )


def thread_rows(messages, as_of):
    for message in messages:
        if message.reply_count:
            yield (
                message.channel_id,
                message.ts,
                message.reply_count,
                len(message.repliers),
                message.latest_reply_ts,
                message.reply_count,
                message.latest_reply_ts,
                as_of,
                as_of,
            )


def walk_row(channel_id, messages, as_of):
    return (
        channel_id,
        messages[0].ts,
        messages[-1].ts,
        len(messages),
        True,
        as_of,
        as_of,
    )


def build(rng, events, members, as_of):
    bots = {member.user_id for member in members if member.is_bot}
    observed_at = datetime.combine(as_of, time(12, 0), tzinfo=timezone.utc)
    events_by_channel = by_channel_day(events)
    messages, threads, walks = [], [], []
    for channel_id in sorted(events_by_channel):
        threaded_messages = assign_threads(rng, channel_messages(rng, channel_id, events_by_channel[channel_id], bots))
        if not threaded_messages:
            continue
        messages.extend(message_row(rng, message, observed_at) for message in threaded_messages)
        threads.extend(thread_rows(threaded_messages, observed_at))
        walks.append(walk_row(channel_id, threaded_messages, observed_at))
    return messages, threads, walks


ARCHIVE_REVISION = 0

ARCHIVE_MESSAGE_COLUMNS = [
    "channel_id", "ts", "revision", "posted_at", "author_id", "author_kind", "subtype",
    "thread_root_ts", "is_reply", "is_broadcast", "reply_count", "reply_users_count",
    "latest_reply_ts", "text_length", "has_text", "file_count", "mention_count",
    "mentioned_ids", "is_question", "is_substantive", "has_link", "emoji_only",
    "reaction_count", "reactor_count", "edited_at", "edited_by", "settled", "first_seen_at",
]


def archive_message_row(row):
    fields = dict(zip(MESSAGE_COLUMNS, row))
    length = fields["text_length"]
    return (
        fields["channel_id"], fields["ts"], ARCHIVE_REVISION, fields["posted_at"],
        fields["author_id"], fields["author_kind"], fields["subtype"], fields["thread_root_ts"],
        fields["is_reply"], fields["subtype"] == "thread_broadcast",
        fields["reply_count"], fields["reply_users_count"], fields["latest_reply_ts"],
        length, None if length is None else length > 0,
        fields["file_count"], fields["mention_count"], fields["mentioned_ids"],
        fields["is_question"], fields["is_substantive"], fields["has_link"], fields["emoji_only"],
        fields["reaction_count"], fields["reactor_count"], fields["edited_at"], fields["edited_by"],
        False, fields["observed_at"],
    )
