import time
from datetime import date

METHOD = "admin.analytics.getAvailableDateRange"
TTL_SECONDS = 3600

_cache = {}


def available(client, kind="member", clock=time.monotonic):
    cached = _cache.get(kind)
    if cached is not None and clock() - cached[0] < TTL_SECONDS:
        return cached[1]
    resp = client.call(METHOD, {"type": kind})
    rng = resp.get("available_date_range") or resp
    window = date.fromisoformat(rng["start_date"]), date.fromisoformat(rng["end_date"])
    _cache[kind] = (clock(), window)
    return window


def available_iso(client, kind="member"):
    start, end = available(client, kind)
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}


def clear():
    _cache.clear()
