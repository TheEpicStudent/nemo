import logging
import threading
import time

from bot.core import loops, session
from lyla import categories, link, numbers, source, status
from lyla.reader import Reader
from lyla.writer import Writer

log = logging.getLogger("lyla")

NAME = "lyla"
READ_SECONDS = 15
CATEGORY_SECONDS = 600
RETRY_SECONDS = 30
CHANNELS = ("fd_lyla_outbox", "fd_infraction_category", "fd_app_setting")

FOREIGN_CASES = """
SELECT count(*) FROM fd.cases c
WHERE c.source_app <> 'lyla' AND c.id = ANY(%s)
  AND NOT EXISTS (SELECT 1 FROM fd.import_map m
                  WHERE m.source_app = 'lyla' AND m.source_table = 'cases'
                    AND m.source_key = c.id::text)
"""

LYLA_NUMBERS = "SELECT case_number FROM cases"

CLEAR_OUTBOX = "DELETE FROM fd.lyla_outbox WHERE applied_at IS NULL"


class Sync:
    def __init__(self):
        self.lyla = None
        self.read_at = 0.0
        self.categories_at = 0.0

    def connection(self):
        if self.lyla is None or self.lyla.closed:
            self.lyla = source.connect()
        return self.lyla

    def drop(self):
        if self.lyla is not None:
            try:
                self.lyla.close()
            except Exception:
                pass
        self.lyla = None

    def cycle(self, force_read=False):
        with session() as conn:
            if not link.is_on(conn):
                return False
            imported = status.imported(conn)
        lyla = self.connection()
        if not imported and not self.import_all(lyla):
            return False
        now = time.monotonic()
        if now - self.categories_at >= CATEGORY_SECONDS:
            with session() as conn:
                categories.mirror(conn, lyla)
            self.categories_at = now
        with session() as conn:
            numbers.refill(conn, lyla)
            status.ran(conn, status.NUMBERS)
        self.write(lyla)
        if force_read or now - self.read_at >= READ_SECONDS:
            self.read(lyla)
            self.read_at = now
        return True

    def import_all(self, lyla):
        lyla_numbers = [row[0] for row in lyla.execute(LYLA_NUMBERS).fetchall()]
        lyla.rollback()
        with session() as conn:
            foreign = conn.execute(FOREIGN_CASES, (lyla_numbers,)).fetchone()[0]
            if foreign:
                status.ran(conn, status.IMPORT, f"{foreign} Nemo case(s) already use LYLA case numbers")
                return False
            status.ran(conn, status.IMPORT, ok=False)
            cleared = conn.execute(CLEAR_OUTBOX).rowcount
        log.info("lyla: importing, cleared %s waiting outbox row(s)", cleared)
        started = time.monotonic()
        try:
            summary = Reader(session, lyla).run()
        except Exception as failure:
            lyla.rollback()
            with session() as conn:
                status.ran(conn, status.IMPORT, failure, ok=False)
            raise
        failed = summary.get("failed")
        with session() as conn:
            status.ran(conn, status.IMPORT, f"{failed} failed" if failed else None, ok=True)
        log.info("lyla: imported in %.0fs, %s", time.monotonic() - started, dict(summary))
        self.categories_at = 0.0
        return True

    def write(self, lyla):
        writer = Writer(session, lyla)
        try:
            more = True
            while more:
                _applied, more = writer.drain()
        except Exception as failure:
            with session() as conn:
                status.ran(conn, status.WRITER, failure)
            raise
        with session() as conn:
            status.ran(conn, status.WRITER)

    def read(self, lyla):
        try:
            summary = Reader(session, lyla).run()
        except Exception as failure:
            lyla.rollback()
            with session() as conn:
                status.ran(conn, status.READER, failure)
            raise
        with session() as conn:
            status.ran(conn, status.READER)
        if summary:
            log.info("lyla: read %s", dict(summary))


def serve(stopping):
    wake = threading.Event()
    sync = Sync()

    def on_notify(channel, payload):
        if channel == "fd_infraction_category":
            sync.categories_at = 0.0
        wake.set()

    loops.start_listener(NAME, CHANNELS, on_notify, stopping)
    while not stopping.is_set():
        wake.clear()
        try:
            sync.cycle()
        except Exception:
            log.exception("lyla: the sync pass failed, trying again in %ss", RETRY_SECONDS)
            sync.drop()
            stopping.wait(RETRY_SECONDS)
            continue
        wake.wait(READ_SECONDS)
    sync.drop()
