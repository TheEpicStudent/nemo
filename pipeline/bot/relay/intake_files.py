import logging

from bot.core import blobs, session, slack_files

log = logging.getLogger("bot.relay")


def download(url, token, limit):
    return slack_files.download(url, token, limit)


def drain(token, limit=20):
    stored_count = 0
    with session() as conn:
        rows = blobs.waiting(conn, limit)

    for file_id, slack_id, url, size, mimetype in rows:
        if not blobs.is_media_type(mimetype):
            with session() as conn:
                blobs.mark_failed(conn, file_id, "refused", blobs.NOT_MEDIA)
            log.info("relay: %s is %s, not an image, video or pdf", slack_id, mimetype)
            continue
        if blobs.exceeds_limit(size):
            with session() as conn:
                blobs.mark_failed(
                    conn, file_id, "too_large", f"{size} bytes is over the {blobs.cap()} byte limit"
                )
            log.info("relay: %s is too large to keep", slack_id)
            continue

        body, state, error = download(url, token, blobs.cap())
        detected = blobs.media_type(body) if state == "stored" else None
        if state == "stored" and detected is None:
            state, error = "refused", blobs.NOT_MEDIA
        elif state == "stored" and detected == "application/pdf":
            error = blobs.pdf_refusal(body)
            if error:
                state = "refused"
        with session() as conn:
            if state == "stored":
                blobs.store_blob(conn, file_id, body, detected)
                stored_count += 1
            else:
                blobs.mark_failed(conn, file_id, state, error)
        log.info("relay: %s is %s", slack_id, state)
    return stored_count
