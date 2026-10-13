import re

import yaml

from ingest.ip_networks import download_cached
from lib.db import ingest_run
from lib.paths import DB_DIR

SOURCE = "throwaway_domains"
SIGNALS_FILE = DB_DIR / "alt_signals.yml"
LIST_URL = ("https://raw.githubusercontent.com/disposable-email-domains/disposable-email-domains/"
            "main/disposable_email_blocklist.conf")
LIST_FILE = "disposable_email_blocklist.conf"
SMALLEST_LIST = 1000
DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")

LOAD_SQL = """
INSERT INTO fd.throwaway_domain (domain, source, refreshed_at)
SELECT domain, source, now() FROM unnest(%s::text[], %s::text[]) AS one (domain, source)
ON CONFLICT (domain) DO UPDATE SET source = EXCLUDED.source, refreshed_at = EXCLUDED.refreshed_at
"""

DROP_SQL = "DELETE FROM fd.throwaway_domain WHERE NOT (domain = ANY(%s::text[]))"


def domains_in(text):
    found = set()
    for line in text.splitlines():
        domain = line.split("#", 1)[0].strip().lower().lstrip("@")
        if DOMAIN.match(domain):
            found.add(domain)
    return found


def curated(config=None):
    config = config or yaml.safe_load(SIGNALS_FILE.read_text())
    return domains_in("\n".join(config.get("throwaway_domains") or []))


def merged(listed, picked):
    rows = {domain: "list" for domain in listed}
    rows.update({domain: "curated" for domain in picked})
    return rows


def run(conn):
    listed = domains_in(download_cached(LIST_FILE, LIST_URL).read_text())
    if len(listed) < SMALLEST_LIST:
        print(f"{SOURCE}: the list holds only {len(listed)} domain(s), keeping the ones already loaded")
        return 0
    rows = merged(listed, curated())
    names = sorted(rows)
    with ingest_run(conn, SOURCE) as counts:
        conn.execute(LOAD_SQL, (names, [rows[name] for name in names]))
        conn.execute(DROP_SQL, (names,))
        conn.commit()
        counts.rows_in = len(names)
    print(f"{SOURCE}: {len(names)} throwaway domain(s), {sum(1 for one in rows.values() if one == 'curated')} curated")
    return len(names)
