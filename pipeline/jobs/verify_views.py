import re
import sys

from dotenv import load_dotenv

from lib.db import connect
from lib.paths import ENV_FILE, WEB_DIR

TABLE_NAME = re.compile(r'self\.table_name\s*=\s*"((?:analytics|ingest)\.[a-z0-9_]+)"')
MODELS = WEB_DIR / "app" / "models"
EXISTS_SQL = """
SELECT 1 FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relname = %s
"""


def declared_relations(texts):
    return sorted({match.group(1) for text in texts for match in TABLE_NAME.finditer(text)})


def rails_relations():
    return declared_relations(path.read_text() for path in MODELS.rglob("*.rb"))


def missing(conn, relations):
    missing_relations = []
    for relation in relations:
        schema, name = relation.split(".", 1)
        if conn.execute(EXISTS_SQL, (schema, name)).fetchone() is None:
            missing_relations.append(relation)
    return missing_relations


def main():
    load_dotenv(ENV_FILE)
    relations = rails_relations()
    with connect() as conn:
        missing_relations = missing(conn, relations)
    if missing_relations:
        print(f"verify_views: {len(missing_relations)} missing relation(s): " + ", ".join(missing_relations))
        return 1
    print(f"verify_views: {len(relations)} relation(s) present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
