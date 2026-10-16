from ingest import channel_month_pull as cm


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def call(self, method, params, max_retries=3):
        self.calls.append(params)
        key = (params.get("query"), params["sort_direction"])
        records = self.pages.get(key, [])
        return {"channel_analytics": records, "num_found": len(records)}


def rec(cid, name):
    return {"channel_id": cid, "name": name}


def test_token_heads_returns_first_character_of_each_token():
    assert cm.token_heads("welcome-to-hack-club") == {"w", "t", "h", "c"}
    assert cm.token_heads("2026-hackathon") == {"2", "h"}


def test_queryable_shards_non_latin_prefixes_are_dropped():
    prefixes = {"a", "z", "0", "9", "é", "ø", "α", "в", "中", "か"}
    assert cm.queryable_shards(prefixes) == ["0", "9", "a", "z"]


def test_token_heads_astral_plane_name_returns_no_shards():
    assert cm.token_heads("𒈙𒈙𒈙") == set()
    assert cm.queryable_shards(cm.token_heads("𒈙𒈙𒈙")) == []


def test_sweep_overlapping_shards_batches_only_new_records():
    client = FakeClient({
        ("a", "asc"): [rec("C1", "alpha"), rec("C2", "banana")],
        ("b", "asc"): [rec("C2", "banana"), rec("C3", "bravo")],
    })
    records, batches = {}, []
    cm.MIN_SECONDS_PER_CALL = 0
    truncated = cm.sweep(client, "2026-08", ["a", "b"], records, batches.append)
    assert truncated == []
    assert sorted(records) == ["C1", "C2", "C3"]
    assert [[r["channel_id"] for r in batch] for batch in batches] == [["C1", "C2"], ["C3"]]


def test_sweep_num_found_over_page_size_returns_truncated_shard():
    class Truncating(FakeClient):
        def call(self, method, params, max_retries=3):
            return {"channel_analytics": [rec("C1", "a")], "num_found": 900}
    cm.MIN_SECONDS_PER_CALL = 0
    cm.SPLIT_DEPTH = 0
    try:
        truncated = cm.sweep(Truncating({}), "2026-08", ["a"], {}, None)
    finally:
        cm.SPLIT_DEPTH = 3
    assert truncated == ["a"]


def test_tail_sweep_adds_only_channels_missing_from_records():
    client = FakeClient({
        (None, "desc"): [rec("C9", "鏡音レン"), rec("C1", "alpha")],
    })
    records = {"C1": rec("C1", "alpha")}
    batches = []
    added = cm.tail_sweep(client, "2026-08", records, batches.append)
    assert added == 1
    assert sorted(records) == ["C1", "C9"]
    assert [r["channel_id"] for r in batches[0]] == ["C9"]
    assert client.calls[0]["sort_direction"] == "desc"
    assert "query" not in client.calls[0]


def test_merge_records_without_new_records_returns_zero():
    records = {"C1": rec("C1", "a")}
    assert cm.merge_records([rec("C1", "a")], records, None) == 0
