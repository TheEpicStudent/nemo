from lyla import link, status

CLAIMED = """
SELECT 1 FROM fd.import_map
WHERE entity_table = 'cases' AND entity_id = %s
  AND source_app = 'lyla' AND source_table = 'case_threads'
LIMIT 1
"""


def waiting(conn, case_id):
    return (link.is_on(conn) and status.imported(conn)
            and conn.execute(CLAIMED, (case_id,)).fetchone() is None)
