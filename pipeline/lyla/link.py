KEY = "lyla.link"
ON = "on"
OFF = "off"

SETTING = "SELECT value FROM fd.app_settings WHERE key = %s"


def is_on(conn):
    row = conn.execute(SETTING, (KEY,)).fetchone()
    return bool(row) and row[0].strip().lower() == ON
