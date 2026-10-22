import logging
import os
import threading

from jobs import case_chat_import, firehose_import
from lyla import source, sync

log = logging.getLogger("lyla")


def spawn(name, target, *args):
    thread = threading.Thread(target=target, args=args, name=name, daemon=True)
    thread.start()
    return thread


def start(client, stopping):
    threads = []
    if os.environ.get(source.URL):
        threads.append(spawn("lyla-sync", sync.serve, stopping))
        threads.append(spawn("lyla-chat-import", case_chat_import.serve, client, stopping))
    if os.environ.get(firehose_import.URL):
        threads.append(spawn("firehose-mirror", firehose_import.serve, stopping))
    if threads:
        log.info("lyla: started %s", ", ".join(thread.name for thread in threads))
    return threads
