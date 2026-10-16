from datetime import date

from jobs import invariants


class OneRow:
    def __init__(self, row):
        self.row = row

    def execute(self, sql, params=None):
        return self

    def fetchone(self):
        return self.row

    def fetchall(self):
        return [self.row] if self.row else []


def test_i10_status_vocabulary_full_constraint_passes():
    conn = OneRow(("CHECK ((status = ANY (ARRAY['running'::text, 'ok'::text, 'failed'::text, "
                   "'skipped'::text, 'partial'::text, 'cancelled'::text, 'abandoned'::text])))",))
    assertion, status, observed, expected = invariants.i10_status_vocabulary(conn)
    assert (assertion, status) == ("I10", "pass")
    assert observed == expected


def test_i10_status_vocabulary_missing_status_value_fails():
    conn = OneRow(("CHECK ((status = ANY (ARRAY['running'::text, 'ok'::text, 'failed'::text])))",))
    assert invariants.i10_status_vocabulary(conn)[1] == "fail"


def test_i10_status_vocabulary_missing_constraint_fails():
    assert invariants.i10_status_vocabulary(OneRow(None))[1] == "fail"


def test_i1_planned_stages_have_rows_passes_only_when_counts_match():
    assert invariants.i1_planned_stages_have_rows(OneRow(("2026-09-05", 20, 20)))[1] == "pass"
    assert invariants.i1_planned_stages_have_rows(OneRow(("2026-09-05", 18, 20)))[1] == "fail"
    assert invariants.i1_planned_stages_have_rows(OneRow(None))[1] == "pass"


def test_i4_counts_nullable_column_with_zero_default_fails():
    class Rows(OneRow):
        def fetchall(self):
            return [("ingest.work_item.fetched", "NO", "0"), ("raw.ingest_run.rows_in", "YES", None)]
    assertion, status, observed, _ = invariants.i4_counts_nullable(Rows(None))
    assert (assertion, status) == ("I4", "fail")
    assert observed == "ingest.work_item.fetched"


def test_severity_of_pass_is_info_fail_is_error_except_i4_warn():
    assert invariants.severity_of("I1", "pass") == "info"
    assert invariants.severity_of("I1", "fail") == "error"
    assert invariants.severity_of("I4", "fail") == "warn"


def test_checks_registry_has_seven_unique_checks():
    names = [check.__name__ for check in invariants.CHECKS]
    assert len(names) == len(set(names)) == 7


class DaySource:
    def __init__(self, rows):
        self.rows = rows

    def execute(self, sql, params=None):
        return self

    def fetchall(self):
        return self.rows


def test_i11_day_sources_recent_fresh_sources_pass():
    conn = DaySource([("member_day", "2026-09-09", 2), ("channel_day", "2026-09-09", 2)])
    assertion, status, observed, _ = invariants.i11_day_sources_recent(conn)
    assert (assertion, status) == ("I11", "pass")
    assert "worst 2d" in observed


def test_i11_day_sources_recent_stale_source_fails_and_is_named():
    conn = DaySource([("member_day", "2026-09-09", 2), ("channel_day", "2026-07-01", 72)])
    assertion, status, observed, _ = invariants.i11_day_sources_recent(conn)
    assert (assertion, status) == ("I11", "fail")
    assert "channel_day stopped at 2026-07-01 (72d)" in observed
    assert "member_day" not in observed


def test_i11_day_sources_recent_passes_at_lag_limit_fails_above():
    assert invariants.DAY_LAG_LIMIT > 2
    conn = DaySource([("member_day", "2026-09-08", invariants.DAY_LAG_LIMIT)])
    assert invariants.i11_day_sources_recent(conn)[1] == "pass"
    conn = DaySource([("member_day", "2026-09-08", invariants.DAY_LAG_LIMIT + 1)])
    assert invariants.i11_day_sources_recent(conn)[1] == "fail"


def test_severity_of_i11_fail_is_error():
    assert invariants.severity_of("I11", "fail") == "error"


class Ledgers:
    def __init__(self, answers):
        self.answers = list(answers)
        self.last = None

    def execute(self, sql, params=None):
        self.last = self.answers.pop(0)
        return self

    def fetchone(self):
        return self.last


DATE_RANGE = (date(2026, 7, 15), date(2026, 9, 11))


def test_i12_day_ledgers_agree_without_slices_passes():
    conn = Ledgers([(None, None), (None, None)])
    assertion, status, observed, _ = invariants.i12_day_ledgers_agree(conn)
    assert (assertion, status) == ("I12", "pass")
    assert "no day source has claimed a slice" in observed


def test_i12_day_ledgers_agree_matching_ledgers_pass():
    conn = Ledgers([DATE_RANGE, (0, 0), DATE_RANGE, (0, 0)])
    _, status, observed, _ = invariants.i12_day_ledgers_agree(conn)
    assert status == "pass"
    assert "2 day source(s) agree" in observed


def test_i12_day_ledgers_agree_complete_slice_without_loaded_day_fails():
    conn = Ledgers([DATE_RANGE, (0, 3), DATE_RANGE, (0, 0)])
    _, status, observed, _ = invariants.i12_day_ledgers_agree(conn)
    assert status == "fail"
    assert "3 complete slice(s) with no loaded day" in observed


def test_i12_day_ledgers_agree_loaded_day_without_slice_fails():
    conn = Ledgers([DATE_RANGE, (0, 0), DATE_RANGE, (4, 0)])
    _, status, observed, _ = invariants.i12_day_ledgers_agree(conn)
    assert status == "fail"
    assert "4 loaded day(s) with no slice" in observed
