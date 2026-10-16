import os
import threading
import time

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from lib.proxy_client import ProxyClient, ProxyError

PREFIX = "INGEST_TOKEN_"
USER_TOKEN_PREFIX = "xoxp-"


def discover(env=None):
    env = env if env is not None else os.environ
    tokens = []
    for name, value in env.items():
        if not name.startswith(PREFIX):
            continue
        index = name[len(PREFIX):]
        if not index.isdigit():
            continue
        token = (value or "").strip()
        if token:
            tokens.append((int(index), token))
    return sorted(tokens, key=lambda pair: pair[0])


def names(env=None):
    return [f"{PREFIX}{index}" for index, _ in discover(env)]


def problems(env=None):
    pool = discover(env)
    first_index_by_token, issues = {}, []
    for index, token in pool:
        if not token.startswith(USER_TOKEN_PREFIX):
            issues.append(f"{PREFIX}{index} is not a user token")
        first_index = first_index_by_token.setdefault(token, index)
        if first_index != index:
            issues.append(f"{PREFIX}{index} repeats {PREFIX}{first_index}")
    return issues


def describe(env=None):
    pool = discover(env)
    if not pool:
        return f"ingest pool: no {PREFIX}n set"
    indexes = ", ".join(str(index) for index, _ in pool)
    pinned = pinned_rate(env)
    pace = (f"pinned at {pinned:.0f}/min each" if pinned is not None
            else f"adaptive from {START_PER_MINUTE:.0f}/min each")
    line = (f"ingest pool: {len(pool)} token(s), {PREFIX}[{indexes}], {pace}, "
            f"{expected_per_minute(env):.0f}/min across the pool")
    issues = problems(env)
    if issues:
        line += "".join(f"\ningest pool: {note}" for note in issues)
    return line


def report(env=None):
    print(describe(env))
    return discover(env)


class ThrottledError(RuntimeError):
    def __init__(self, retry_after):
        super().__init__(f"Slack rate limit, retry after {retry_after}s")
        self.retry_after = retry_after


TIER3 = 50
START_PER_MINUTE = float(TIER3)
MIN_PER_MINUTE = 20.0
MAX_PER_MINUTE = 600.0
RATE_INCREASE_PER_MINUTE = 15.0
RATE_INCREASE_AFTER = 20.0
BACKOFF = 0.75
BACKOFF_AFTER = 15.0
CEILING_MARGIN = 0.95
CEILING_RAISE_AFTER = 600.0
CEILING_RAISE_FACTOR = 1.1
BURST = 5.0
COOLDOWN_MAX_SECONDS = 300.0
WAIT_SLICE = 5.0
WAIT_CEILING = 900
SHARD_TIMEOUT = 60

_adaptive_rates = {}
_adaptive_rates_lock = threading.Lock()


def pinned_rate(env=None):
    env = env if env is not None else os.environ
    configured = (env.get("INGEST_SHARD_PER_MINUTE") or "").strip()
    return float(configured) if configured else None


def adaptive_rate(index):
    with _adaptive_rates_lock:
        return _adaptive_rates.get(index, START_PER_MINUTE)


def store_rate(index, per_minute):
    with _adaptive_rates_lock:
        _adaptive_rates[index] = per_minute


def expected_per_minute(env=None):
    pool = discover(env)
    if not pool:
        return None
    pinned = pinned_rate(env)
    if pinned is not None:
        return pinned * len(pool)
    return sum(adaptive_rate(index) for index, _ in pool)


class Bucket:
    def __init__(self, per_minute, burst=BURST, clock=time.monotonic):
        self.per_minute = float(per_minute)
        self.burst = float(burst)
        self.tokens = float(burst)
        self.clock = clock
        self.filled_at = clock()
        self.lock = threading.Lock()

    def take(self):
        with self.lock:
            now = self.clock()
            rate = self.per_minute / 60.0
            self.tokens = min(self.burst, self.tokens + (now - self.filled_at) * rate)
            self.filled_at = now
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True, 0.0
            return False, (1.0 - self.tokens) / rate


class Shard:
    def __init__(self, index, token, per_minute=None, clock=time.monotonic):
        self.index = index
        self.token = token
        configured_rate = pinned_rate() if per_minute is None else float(per_minute)
        self.pinned = configured_rate is not None
        self.per_minute = configured_rate if self.pinned else adaptive_rate(index)
        self.clock = clock
        self.buckets = {}
        self.cooldown_until = {}
        self._client = None
        self.lock = threading.Lock()
        self.acquired_count = 0
        self.throttles = 0
        self.changed_at = clock()
        self.ceiling = None
        self.throttled_at = None
        self.exhausted = False

    def name(self):
        return f"{PREFIX}{self.index}"

    def client(self, timeout=SHARD_TIMEOUT):
        with self.lock:
            if self._client is None:
                self._client = WebClient(token=self.token, timeout=timeout, retry_handlers=[])
            return self._client

    def invoke(self, method, params, timeout=SHARD_TIMEOUT):
        try:
            return self.client(timeout).api_call(method, http_verb="GET", params=params).data
        except SlackApiError as failure:
            response = getattr(failure, "response", None)
            status = getattr(response, "status_code", None)
            if status == 429:
                headers = getattr(response, "headers", {}) or {}
                raise ThrottledError(float(headers.get("Retry-After", 1) or 1)) from failure
            raise

    def cooldown_remaining(self, method=None):
        if method is not None:
            return max(0.0, self.cooldown_until.get(method, 0.0) - self.clock())
        remaining = [until - self.clock() for until in self.cooldown_until.values()]
        return max([0.0, *remaining])

    def bucket(self, method):
        with self.lock:
            if method not in self.buckets:
                self.buckets[method] = Bucket(self.per_minute, clock=self.clock)
            return self.buckets[method]

    def take(self, method):
        cooldown_seconds = self.cooldown_remaining(method)
        if cooldown_seconds > 0:
            return False, cooldown_seconds
        ok, wait = self.bucket(method).take()
        with self.lock:
            if ok:
                self.acquired_count += 1
            else:
                self.exhausted = True
        return ok, wait

    def _retune(self, per_minute):
        per_minute = min(max(float(per_minute), MIN_PER_MINUTE), MAX_PER_MINUTE)
        self.per_minute = per_minute
        for bucket in self.buckets.values():
            bucket.per_minute = per_minute
        self.changed_at = self.clock()
        store_rate(self.index, per_minute)
        return per_minute

    def mark_success(self):
        if self.pinned:
            return self.per_minute
        with self.lock:
            now = self.clock()
            if not self.exhausted or now - self.changed_at < RATE_INCREASE_AFTER:
                return self.per_minute
            self.exhausted = False
            target = self.per_minute + RATE_INCREASE_PER_MINUTE
            if self.ceiling is not None:
                if now - self.throttled_at >= CEILING_RAISE_AFTER:
                    self.ceiling *= CEILING_RAISE_FACTOR
                    self.throttled_at = now
                target = min(target, self.ceiling * CEILING_MARGIN)
            return self._retune(target)

    def cooldown(self, method, seconds):
        seconds = min(max(float(seconds), 0.0), COOLDOWN_MAX_SECONDS)
        with self.lock:
            now = self.clock()
            self.throttles += 1
            already_cooling = self.cooldown_until.get(method, 0.0) > now
            recently_throttled = self.throttled_at is not None and now - self.throttled_at < BACKOFF_AFTER
            self.cooldown_until[method] = now + seconds
            if not self.pinned and not already_cooling and not recently_throttled:
                self.ceiling = self.per_minute
                self.throttled_at = now
                self._retune(self.per_minute * BACKOFF)
        return seconds


class Pool:
    def __init__(self, env=None, per_minute=None, clock=time.monotonic):
        self.clock = clock
        self.shards = [
            Shard(index, token, per_minute=per_minute, clock=clock)
            for index, token in discover(env)
        ]
        self.cursor = 0
        self.lock = threading.Lock()

    def __len__(self):
        return len(self.shards)

    def per_minute(self):
        return sum(shard.per_minute for shard in self.shards)

    def acquire(self, method):
        if not self.shards:
            return None, 0.0
        with self.lock:
            start = self.cursor
            self.cursor = (self.cursor + 1) % len(self.shards)
        waits = []
        for step in range(len(self.shards)):
            shard = self.shards[(start + step) % len(self.shards)]
            ok, wait = shard.take(method)
            if ok:
                return shard, 0.0
            waits.append(wait)
        return None, min(waits)

    def cooldown(self, shard, method, seconds):
        return shard.cooldown(method, seconds)

    def rates(self):
        return [
            (shard.name(), shard.acquired_count, shard.throttles, round(shard.cooldown_remaining(), 1))
            for shard in self.shards
        ]

    def summary(self):
        if not self.shards:
            return "no pool"
        parts = []
        for shard, acquired_count, throttles, cooling in self.rates():
            piece = f"{shard.replace(PREFIX, 's')} {acquired_count}"
            if throttles:
                piece += f"/{throttles}t"
            if cooling:
                piece += f" cooldown {cooling:.0f}s"
            parts.append(piece)
        return (f"{len(self.shards)} shard(s): " + ", ".join(parts)
                + f" @{self.per_minute():.0f}/min")


class PoolUnavailableError(RuntimeError):
    pass


class ShardedClient(ProxyClient):
    def __init__(self, pool=None, read_timeout=SHARD_TIMEOUT, deadline_seconds=None, sleep=time.sleep):
        self.pool = pool if pool is not None else Pool()
        if not len(self.pool):
            raise PoolUnavailableError(f"no {PREFIX}n set")
        self.read_timeout = read_timeout
        self.deadline_seconds = deadline_seconds if deadline_seconds is not None else read_timeout
        self.last_num_found = None
        self.sleep = sleep
        self.wait_ceiling = max(WAIT_CEILING, self.deadline_seconds or 0)

    @classmethod
    def for_source(cls, key, **kwargs):
        from lib import sources
        budget = sources.unit_budget_seconds(key)
        return cls(deadline_seconds=budget, read_timeout=min(SHARD_TIMEOUT, budget), **kwargs)

    def call(self, method, params=None, max_retries=3, credential="internal"):
        cleaned = {k: v for k, v in dict(params or {}).items() if v is not None}
        waited = 0.0
        throttles = 0
        while True:
            shard, wait = self.pool.acquire(method)
            if shard is None:
                pause = min(max(wait, 0.01), WAIT_SLICE)
                waited += pause
                if waited > self.wait_ceiling:
                    raise ProxyError(f"{method}: no shard available after {waited:.0f}s")
                self.sleep(pause)
                continue
            try:
                data = shard.invoke(method, cleaned, timeout=self.read_timeout)
            except ThrottledError as throttle:
                throttles += 1
                self.pool.cooldown(shard, method, throttle.retry_after)
                if throttles > max(max_retries, len(self.pool) * 2):
                    raise ProxyError(
                        f"{method}: {throttles} throttle(s) across {len(self.pool)} shard(s)"
                    ) from throttle
                continue
            shard.mark_success()
            num_found = data.get("num_found")
            if num_found is not None:
                self.last_num_found = num_found
            return data


def client_for(key, **kwargs):
    try:
        client = ShardedClient.for_source(key, **kwargs)
    except PoolUnavailableError:
        return ProxyClient.for_source(key, **kwargs), "proxy"
    return client, f"{len(client.pool)} shard(s)"

