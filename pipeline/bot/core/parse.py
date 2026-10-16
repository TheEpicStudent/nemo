import hashlib
import json
import re
from datetime import datetime, timezone

ARCHIVE_LINK = re.compile(
    r"https://[a-zA-Z0-9._-]+\.slack\.com/archives/([A-Z][A-Z0-9]+)/p(\d{10})(\d{6})"
    r"(?:\?([^\s<>|]*))?"
)

THREAD_TS = re.compile(r"(?:^|[?&]|&amp;)thread_ts=(\d{1,12}\.\d{6})")


def posted_at(ts):
    if ts is None:
        return datetime.now(tz=timezone.utc)

    return datetime.fromtimestamp(float(ts), tz=timezone.utc)


def digest(body, blocks, attachments):
    payload = json.dumps(
        [body or "", blocks or [], attachments or []],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def thread_of(query):
    match = THREAD_TS.search(query or "")
    return match.group(1) if match else None


def link_target(url):
    match = ARCHIVE_LINK.search(url or "")
    if not match:
        return None
    channel_id, seconds, micros, query = match.groups()
    return channel_id, f"{seconds}.{micros}", thread_of(query)


KIND_PRECEDENCE = ("forward", "unfurl", "link")


def share_timestamps(share):
    target = link_target(share["permalink"]) if share["permalink"] else None
    return {share["source_ts"], target[1] if target else None} - {None}


def same_message(one, other):
    if one["source_channel_id"] != other["source_channel_id"]:
        return False

    one_timestamps, other_timestamps = share_timestamps(one), share_timestamps(other)
    if one_timestamps and other_timestamps:
        return bool(one_timestamps & other_timestamps)

    return one["permalink"] == other["permalink"]


def merge(target, share):
    for field, value in share.items():
        if field in ("kind", "is_reachable"):
            continue
        if target.get(field) is None and value is not None:
            target[field] = value

    target["is_reachable"] = target["is_reachable"] or share["is_reachable"]
    target["kind"] = min(target["kind"], share["kind"], key=KIND_PRECEDENCE.index)


def add_share(out, share):
    for existing in out:
        if same_message(existing, share):
            merge(existing, share)
            return
    out.append(share)


def shares(event):
    out = []

    for attachment in event.get("attachments") or []:
        if not isinstance(attachment, dict):
            continue
        url = (
            attachment.get("permalink")
            or attachment.get("from_url")
            or attachment.get("title_link")
        )
        target = link_target(url)
        forwarded = bool(attachment.get("is_share"))
        unfurled = bool(attachment.get("is_msg_unfurl"))
        if not (forwarded or unfurled or target):
            continue

        channel_id = attachment.get("channel_id") or (target[0] if target else None)
        ts = attachment.get("ts") or (target[1] if target else None)
        if not url and not (channel_id and ts):
            continue

        add_share(
            out,
            {
                "kind": "forward" if forwarded else "unfurl",
                "source_channel_id": channel_id,
                "source_channel_name": attachment.get("channel_name"),
                "source_ts": str(ts) if ts else None,
                "source_thread_ts": attachment.get("thread_ts")
                or (target[2] if target else None),
                "source_author_user_id": attachment.get("author_id"),
                "source_body": attachment.get("text") or attachment.get("fallback"),
                "permalink": url,
                "is_reachable": bool(
                    attachment.get("text")
                    or attachment.get("fallback")
                    or attachment.get("author_id")
                ),
                "raw": attachment,
            }
        )

    for url in ARCHIVE_LINK.findall(event.get("text") or ""):
        channel_id, ts, parent = url[0], f"{url[1]}.{url[2]}", thread_of(url[3])
        add_share(
            out,
            {
                "kind": "link",
                "source_channel_id": channel_id,
                "source_channel_name": None,
                "source_ts": ts,
                "source_thread_ts": parent,
                "source_author_user_id": None,
                "source_body": None,
                "permalink": None,
                "is_reachable": False,
                "raw": None,
            }
        )

    return out


def iter_files(event):
    for entry in event.get("files") or []:
        yield entry, False
    for attachment in event.get("attachments") or []:
        if isinstance(attachment, dict) and attachment.get("is_share"):
            for entry in attachment.get("files") or []:
                yield entry, True


def files(event):
    out = []
    processed_ids = set()
    for entry, forwarded in iter_files(event):
        if not isinstance(entry, dict) or not entry.get("id"):
            continue
        if entry["id"] in processed_ids:
            continue
        processed_ids.add(entry["id"])

        mode = entry.get("mode")
        external = bool(entry.get("is_external")) or mode == "external"
        tombstoned = bool(entry.get("is_tombstoned")) or mode == "tombstone"
        hidden = bool(entry.get("is_hidden_by_limit"))

        if tombstoned or hidden:
            state, error = "gone", None
        elif external or not entry.get("url_private"):
            state, error = "skipped", None
        else:
            state, error = "pending", None

        created = entry.get("created")
        out.append(
            {
                "slack_file_id": entry["id"],
                "name": entry.get("name"),
                "title": entry.get("title"),
                "mimetype": entry.get("mimetype"),
                "filetype": entry.get("filetype"),
                "mode": mode,
                "size_bytes": entry.get("size"),
                "original_w": to_int(entry.get("original_w")),
                "original_h": to_int(entry.get("original_h")),
                "is_external": external,
                "external_type": entry.get("external_type"),
                "external_url": entry.get("external_url"),
                "permalink": entry.get("permalink"),
                "url_private": entry.get("url_private"),
                "uploaded_by": entry.get("user"),
                "is_tombstoned": tombstoned,
                "is_hidden_by_limit": hidden,
                "fetch_state": state,
                "fetch_error": error,
                "created_at": posted_at(created) if created else None,
                "forwarded": forwarded,
            }
        )
    return out


def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
