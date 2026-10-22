import os

import psycopg

URL = "LYLA_DATABASE_URL"


def connect():
    return psycopg.connect(os.environ[URL])
