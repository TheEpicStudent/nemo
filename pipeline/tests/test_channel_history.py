from ingest import channel_history_pull as history


def test_walk_params_oldest_and_latest_set_bounds_with_exclusive_latest():
    assert history.walk_params("C1") == {"channel": "C1"}
    assert history.walk_params("C1", oldest="1700000000.000100") == {"channel": "C1", "oldest": "1700000000.000100"}
    assert history.walk_params("C1", latest="1600000000.000000") == {
        "channel": "C1", "latest": "1600000000.000000", "inclusive": False,
    }


def test_pass_order_puts_backfill_first_while_channels_remain():
    assert history.pass_order(1188) == ("backfill", "tail")
    assert history.pass_order(0) == ("tail", "backfill")
    assert history.pass_order(1188, channels=["C1"]) == ("backfill",)
    assert history.pass_order(0, channels=["C1"]) == ("backfill",)


def test_backfill_share_returns_full_batch_while_channels_remain():
    assert history.backfill_share(200, remaining=1188) == 200
    assert history.backfill_share(200, remaining=0) == 50
    assert history.backfill_share(200, remaining=0, full=True) == 200
    assert history.backfill_share(2, remaining=0) == 1


def test_revisit_from_subtracts_lookback_and_clamps_at_zero():
    week = history.LOOKBACK_DAYS * 86400
    assert history.revisit_from("1700000000.000000") == f"{1700000000 - week:.6f}"
    assert history.revisit_from("10.000000") == "0.000000"
    assert history.revisit_from("not a ts") == "not a ts"


def test_backfill_and_tail_selects_filter_history_complete_and_archived():
    assert "coalesce(w.history_complete, false) = false" in history.BACKFILL_SELECT
    assert "d.archived IS NOT TRUE" in history.TAIL_SELECT
    assert history.BACKFILL_KIND != history.TAIL_KIND


def test_tail_select_excludes_archived_channels_backfill_select_includes_them():
    assert "d.archived IS NOT TRUE" not in history.BACKFILL_SELECT, \
        "the backfill has to reach archived channels, their history is still readable"
    assert "d.archived IS NOT TRUE" in history.TAIL_SELECT, \
        "an archived channel takes no new messages, so the tail must never re-read it"
    assert "coalesce(w.history_complete, false) = false" in history.BACKFILL_SELECT, \
        "once its walk has reached the start an archived channel drops out for good"


def test_backfill_select_orders_live_channels_before_archived():
    assert "CASE WHEN d.archived THEN 2000 ELSE 0 END" in history.BACKFILL_SELECT
