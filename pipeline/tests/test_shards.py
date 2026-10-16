from lib import shards


def test_discover_empty_env_has_no_pool():
    assert shards.discover({}) == []
    assert shards.names({}) == []
    assert shards.problems({}) == []
    assert "no INGEST_TOKEN_n set" in shards.describe({})


def test_discover_orders_tokens_by_numeric_index():
    env = {
        "INGEST_TOKEN_10": "xoxp-ten",
        "INGEST_TOKEN_2": "xoxp-two",
        "INGEST_TOKEN_1": "xoxp-one",
        "PGHOST": "irrelevant",
    }
    assert shards.discover(env) == [(1, "xoxp-one"), (2, "xoxp-two"), (10, "xoxp-ten")]
    assert shards.names(env) == ["INGEST_TOKEN_1", "INGEST_TOKEN_2", "INGEST_TOKEN_10"]


def test_discover_skips_blank_nameless_and_non_numeric_tokens():
    env = {
        "INGEST_TOKEN_1": "xoxp-one",
        "INGEST_TOKEN_3": "  ",
        "INGEST_TOKEN_7": "xoxp-seven",
        "INGEST_TOKEN_": "xoxp-nameless",
        "INGEST_TOKEN_TWO": "xoxp-worded",
    }
    assert shards.discover(env) == [(1, "xoxp-one"), (7, "xoxp-seven")]


def test_describe_reports_count_without_tokens():
    env = {"INGEST_TOKEN_1": "xoxp-secret-one", "INGEST_TOKEN_2": "xoxp-secret-two"}
    line = shards.describe(env)
    assert "2 token(s)" in line
    assert "INGEST_TOKEN_[1, 2]" in line
    assert "secret" not in line


def test_problems_bot_token_is_reported():
    env = {"INGEST_TOKEN_1": "xoxb-a-bot-token"}
    problems = shards.problems(env)
    assert len(problems) == 1
    assert "not a user token" in problems[0]
    assert "not a user token" in shards.describe(env)


def test_problems_repeated_token_is_reported():
    env = {"INGEST_TOKEN_1": "xoxp-same", "INGEST_TOKEN_2": "xoxp-same"}
    problems = shards.problems(env)
    assert any("repeats INGEST_TOKEN_1" in note for note in problems)


def test_problems_healthy_pool_is_empty():
    env = {"INGEST_TOKEN_1": "xoxp-one", "INGEST_TOKEN_2": "xoxp-two"}
    assert shards.problems(env) == []
    assert "\n" not in shards.describe(env)


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


def pool_of(n, per_minute=50.0, clock=None):
    clock = clock or Clock()
    env = {f"INGEST_TOKEN_{i}": f"xoxp-{i}" for i in range(1, n + 1)}
    return shards.Pool(env=env, per_minute=per_minute, clock=clock), clock


def grants_within(seconds, n, per_minute=50.0):
    pool, clock = pool_of(n, per_minute)
    granted = 0
    while clock.t < seconds:
        shard, wait = pool.acquire("conversations.replies")
        if shard:
            granted += 1
        else:
            clock.advance(max(wait, 0.01))
    return granted


def test_pool_per_minute_sums_shard_rates():
    pool, _ = pool_of(4, per_minute=50.0)
    assert len(pool) == 4
    assert pool.per_minute() == 200.0


def test_pool_grants_scale_linearly_with_shard_count():
    single_shard = grants_within(60.0, 1)
    assert single_shard == grants_within(60.0, 1)
    for n in (2, 3, 5):
        assert grants_within(60.0, n) == single_shard * n


def test_pool_acquire_empty_pool_returns_none_without_wait():
    pool = shards.Pool(env={})
    assert pool.acquire("conversations.replies") == (None, 0.0)


def test_pool_acquire_skips_cooled_down_shard():
    pool, _ = pool_of(2)
    first, _ = pool.acquire("m")
    pool.cooldown(first, "m", 30)
    for _ in range(3):
        acquired, wait = pool.acquire("m")
        assert acquired is not first
        assert wait == 0.0


def test_pool_acquire_all_cooled_down_waits_shortest_remaining():
    pool, clock = pool_of(2)
    a, b = pool.shards
    pool.cooldown(a, "m", 45)
    pool.cooldown(b, "m", 12)
    acquired, wait = pool.acquire("m")
    assert acquired is None
    assert wait == 12.0
    clock.advance(12.1)
    acquired, _ = pool.acquire("m")
    assert acquired is b


def test_pool_cooldown_applies_per_method():
    pool, _ = pool_of(1)
    shard, _ = pool.acquire("conversations.replies")
    pool.cooldown(shard, "conversations.replies", 60)
    acquired, wait = pool.acquire("conversations.history")
    assert acquired is shard
    assert wait == 0.0
    acquired_on_parked, parked_wait = pool.acquire("conversations.replies")
    assert acquired_on_parked is None
    assert parked_wait == 60.0


def test_pool_acquire_round_robin_spreads_evenly():
    pool, clock = pool_of(5)
    for _ in range(300):
        shard, wait = pool.acquire("m")
        if not shard:
            clock.advance(wait)
    counts = [count for _, count, _, _ in pool.rates()]
    assert max(counts) - min(counts) <= 1


def test_pool_cooldown_caps_seconds_and_clamps_negative():
    pool, _ = pool_of(1)
    shard = pool.shards[0]
    assert pool.cooldown(shard, "m", 10_000) == shards.COOLDOWN_MAX_SECONDS
    assert pool.cooldown(shard, "m", -5) == 0.0


def test_pool_rates_include_names_not_tokens():
    pool, _ = pool_of(2)
    pool.acquire("m")
    line = str(pool.rates())
    assert "INGEST_TOKEN_1" in line
    assert "xoxp" not in line


def fake_pool(n, per_minute=600.0, throttle_first=()):
    clock = Clock()
    env = {f"INGEST_TOKEN_{i}": f"xoxp-{i}" for i in range(1, n + 1)}
    pool = shards.Pool(env=env, per_minute=per_minute, clock=clock)
    invoked = []
    for shard in pool.shards:
        def invoke(method, params, timeout=None, _s=shard):
            invoked.append(_s.name())
            if _s.name() in throttle_first and invoked.count(_s.name()) == 1:
                raise shards.ThrottledError(5)
            cursor = params.get("cursor")
            page = 0 if not cursor else int(cursor)
            next_cursor = str(page + 1) if page + 1 < 3 else ""
            return {
                "messages": [{"ts": f"{page}.{i}"} for i in range(2)],
                "response_metadata": {"next_cursor": next_cursor},
            }
        shard.invoke = invoke
    return pool, clock, invoked


def walk(client):
    return list(client.paginate(
        "conversations.replies", {"channel": "C1", "ts": "1"}, "messages",
        page_size=200, cursor_param="cursor", page_param="limit",
        cursor_field="response_metadata.next_cursor", credential="admin",
    ))


def test_sharded_client_paginate_walks_every_page():
    pool, clock, invoked = fake_pool(2)
    client = shards.ShardedClient(pool=pool, sleep=clock.advance)
    assert len(walk(client)) == 6
    assert len(invoked) == 3


def test_sharded_client_paginate_alternates_shards():
    pool, clock, invoked = fake_pool(2)
    client = shards.ShardedClient(pool=pool, sleep=clock.advance)
    walk(client)
    assert invoked == ["INGEST_TOKEN_1", "INGEST_TOKEN_2", "INGEST_TOKEN_1"]


def test_sharded_client_throttle_cools_shard_and_other_shard_finishes():
    pool, clock, invoked = fake_pool(2, throttle_first=("INGEST_TOKEN_1",))
    client = shards.ShardedClient(pool=pool, sleep=clock.advance)
    assert len(walk(client)) == 6
    first, second = pool.shards
    assert first.throttles == 1
    assert first.cooldown_remaining("conversations.replies") == 5.0
    assert second.acquired_count == 3


def test_sharded_client_single_throttled_shard_waits_and_completes():
    pool, clock, invoked = fake_pool(1, throttle_first=("INGEST_TOKEN_1",))
    client = shards.ShardedClient(pool=pool, sleep=clock.advance)
    assert len(walk(client)) == 6
    assert pool.shards[0].throttles == 1


def test_sharded_client_paginate_records_last_num_found():
    pool, clock, _ = fake_pool(1)
    pool.shards[0].invoke = lambda m, p, timeout=None: {
        "messages": [{"ts": "1"}], "num_found": 4242,
        "response_metadata": {"next_cursor": ""},
    }
    client = shards.ShardedClient(pool=pool, sleep=clock.advance)
    list(client.paginate("conversations.replies", {"channel": "C1"}, "messages",
                         cursor_field="response_metadata.next_cursor"))
    assert client.last_num_found == 4242


def test_sharded_client_empty_pool_raises_pool_unavailable():
    import pytest

    with pytest.raises(shards.PoolUnavailableError):
        shards.ShardedClient(pool=shards.Pool(env={}))


def test_pool_summary_lists_shards_throttles_and_no_tokens():
    pool, _ = pool_of(2)
    pool.acquire("m")
    pool.acquire("m")
    pool.cooldown(pool.shards[0], "m", 7)
    line = pool.summary()
    assert line.startswith("2 shard(s): ")
    assert "s1" in line and "s2" in line
    assert "1t" in line
    assert "xoxp" not in line
    assert shards.Pool(env={}).summary() == "no pool"


def test_shard_checks_healthy_probes_pass():
    from checks import shards as check

    probes = [
        (1, ({"ok": True, "team_id": "T1", "user_id": "U1"}, None)),
        (2, ({"ok": True, "team_id": "T1", "user_id": "U1"}, None)),
    ]
    assert check.pool_configured(None, probes)[1] == "pass"
    assert check.tokens_valid(None, probes)[1] == "pass"
    assert check.tokens_are_user_tokens(None, probes)[1] == "pass"
    assert check.tokens_single_workspace(None, probes)[1] == "pass"


def test_shard_checks_invalid_bot_and_mixed_workspace_tokens_fail():
    from checks import shards as check

    invalid = [(1, (None, "invalid_auth"))]
    assert check.tokens_valid(None, invalid)[1] == "fail"
    assert "invalid_auth" in check.tokens_valid(None, invalid)[2]

    bot = [(1, ({"ok": True, "team_id": "T1", "bot_id": "B1"}, None))]
    assert check.tokens_are_user_tokens(None, bot)[1] == "fail"

    mixed_workspaces = [
        (1, ({"ok": True, "team_id": "T1"}, None)),
        (2, ({"ok": True, "team_id": "T2"}, None)),
    ]
    assert check.tokens_single_workspace(None, mixed_workspaces)[1] == "fail"


def test_pool_configured_without_probes_warns():
    from checks import shards as check

    assertion, status, observed, _ = check.pool_configured(None, [])
    assert status == "warn"
    assert "stay on the proxy" in observed
    assert check.severity_of(assertion, status) == "warn"


def test_bucket_take_concurrent_callers_never_exceed_burst():
    import threading
    import time as clocklib

    def yielding_clock():
        clocklib.sleep(0)
        return 0.0

    bucket = shards.Bucket(per_minute=6000.0, burst=50.0, clock=yielding_clock)
    granted = []
    barrier = threading.Barrier(20)

    def acquire_repeatedly():
        barrier.wait()
        for _ in range(20):
            ok, _ = bucket.take()
            if ok:
                granted.append(1)

    threads = [threading.Thread(target=acquire_repeatedly) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(granted) == 50


def test_pool_acquire_concurrent_callers_spread_across_shards():
    import threading
    from collections import Counter

    pool, _ = pool_of(5, per_minute=60000.0)
    acquired_names = []
    lock = threading.Lock()
    barrier = threading.Barrier(20)

    def acquire_repeatedly():
        barrier.wait()
        for _ in range(50):
            shard, _ = pool.acquire("m")
            if shard:
                with lock:
                    acquired_names.append(shard.name())

    threads = [threading.Thread(target=acquire_repeatedly) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    per_shard = Counter(acquired_names)
    assert len(per_shard) == 5
    assert max(per_shard.values()) - min(per_shard.values()) <= len(acquired_names) // 10
    assert sum(per_shard.values()) == sum(s.acquired_count for s in pool.shards)


def test_pool_cooldown_concurrent_throttles_match_acquired_count():
    import threading

    pool, _ = pool_of(3, per_minute=60000.0)
    barrier = threading.Barrier(15)

    def acquire_and_release():
        barrier.wait()
        for _ in range(30):
            shard, _ = pool.acquire("m")
            if shard:
                pool.cooldown(shard, "m", 0)

    threads = [threading.Thread(target=acquire_and_release) for _ in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(s.throttles for s in pool.shards) == sum(s.acquired_count for s in pool.shards)
