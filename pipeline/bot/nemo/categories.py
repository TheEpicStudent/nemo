import threading

from bot.core import session

ALL = """
SELECT key, label, retired_at IS NULL
FROM fd.infraction_categories
ORDER BY position, key
"""

_labels = {}
_active = []
_loaded = False
_lock = threading.Lock()


def refresh(conn):
    global _loaded
    rows = conn.execute(ALL).fetchall()
    with _lock:
        _labels.clear()
        _labels.update({key: label for key, label, _active_now in rows})
        _active[:] = [key for key, _label, active_now in rows if active_now]
        _loaded = True
    return len(rows)


def ensure_loaded():
    if _loaded:
        return
    with session() as conn:
        refresh(conn)


def active():
    ensure_loaded()
    with _lock:
        return {key: _labels[key] for key in _active}


def label(key):
    if not key:
        return None
    ensure_loaded()
    with _lock:
        return _labels.get(key, key.replace("_", " "))
