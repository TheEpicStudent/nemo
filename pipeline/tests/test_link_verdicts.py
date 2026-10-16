import pathlib

import pytest

from jobs import link_verdicts as verdicts
from jobs.link_verdicts import VerdictError


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Conn:
    def __init__(self, existing=None, members=()):
        self.existing = dict(existing or {})
        self.members = set(members)
        self.calls = []
        self.committed = False

    def execute(self, sql, params=None):
        self.calls.append((sql.strip(), params))
        if sql == verdicts.KNOWN_SQL:
            return Result([(one,) for one in params[0] if one in self.members])
        if sql == verdicts.EXISTING_SQL:
            existing = self.existing.get(tuple(params))
            return Result([existing] if existing else [])
        if sql == verdicts.INSERT_SQL:
            return Result([(41,)])
        return Result([])

    def commit(self):
        self.committed = True

    def args_for(self, prefix):
        return [params for sql, params in self.calls if sql.startswith(prefix)]


def test_ordered_returns_lowest_id_first():
    assert verdicts.ordered("U02", "U01") == ("U01", "U02")
    assert verdicts.ordered("U01", "U02") == ("U01", "U02")


def test_verb_for_maps_verdicts_to_linked_or_unlinked():
    assert verdicts.verb_for("same_person") == "linked"
    assert verdicts.verb_for("allowed_alt") == "linked"
    assert verdicts.verb_for("different_people") == "unlinked"


def test_verdicts_match_migration_check_constraint():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations"
           / "0223_link_verdict_drop_household.sql").read_text()
    for verdict in verdicts.VERDICTS:
        assert f"'{verdict}'" in sql


def test_planned_splits_ids_on_commas_and_spaces():
    planned = verdicts.planned("U09", "U01", {"same_person": ["U02,U03", " U04 "], "different_people": ["U05"]})

    assert planned == {"U02": "same_person", "U03": "same_person", "U04": "same_person",
                       "U05": "different_people"}


def test_planned_account_under_two_verdicts_raises_verdict_error():
    with pytest.raises(VerdictError, match="U02 is listed under both"):
        verdicts.planned("U09", "U01", {"same_person": ["U02"], "different_people": ["U02"]})


def test_planned_main_account_in_verdict_raises_verdict_error():
    with pytest.raises(VerdictError, match="main account"):
        verdicts.planned("U09", "U01", {"same_person": ["U01"]})


def test_planned_malformed_ids_raise_verdict_error():
    with pytest.raises(VerdictError, match="nobody, x1"):
        verdicts.planned("nobody", "U01", {"same_person": ["x1", "U02"]})


def test_planned_empty_verdicts_raise_verdict_error():
    with pytest.raises(VerdictError, match="--same-person"):
        verdicts.planned("U09", "U01", {})


def test_record_new_pair_inserts_verdict_and_audit_row():
    conn = Conn()

    assert verdicts.record(conn, "U09", "U05", "U02", "same_person") == "recorded"

    assert conn.args_for("INSERT INTO fd.member_link_verdict") == [("U02", "U05", "same_person", "U09", None)]
    [row] = conn.args_for("INSERT INTO fd.audit")
    assert row[0] == "U09"
    assert row[2:5] == ("member_link_verdict", 41, "linked")
    assert row[5] is None
    assert row[6].obj["verdict"] == "same_person"
    assert row[8] == "U02"


def test_record_same_verdict_returns_unchanged_without_writes():
    conn = Conn(existing={("U02", "U05"): (7, "same_person", "U08", None)})

    assert verdicts.record(conn, "U09", "U05", "U02", "same_person") == "unchanged"

    assert conn.args_for("UPDATE") == []
    assert conn.args_for("INSERT") == []


def test_record_changed_verdict_preserves_note_and_audits_previous_verdict():
    conn = Conn(existing={("U02", "U05"): (7, "same_person", "U08", "shared a laptop")})

    assert verdicts.record(conn, "U09", "U05", "U02", "different_people") == "changed"

    assert conn.args_for("UPDATE fd.member_link_verdict") == [("different_people", "U09", "shared a laptop", 7)]
    [row] = conn.args_for("INSERT INTO fd.audit")
    assert row[4] == "unlinked"
    assert row[5].obj == {"verdict": "same_person", "decided_by": "U08", "note": "shared a laptop"}
    assert row[6].obj["verdict"] == "different_people"


def test_run_unknown_accounts_raises_before_any_insert():
    conn = Conn(members={"U09", "U05"})

    with pytest.raises(VerdictError, match="not in fd.member: U02"):
        verdicts.run(conn, "U09", "U05", {"U02": "same_person"})

    assert conn.args_for("INSERT") == []
    assert not conn.committed


def test_run_two_pairs_records_both_and_commits():
    conn = Conn(members={"U09", "U05", "U02", "U03"})

    counts = verdicts.run(conn, "U09", "U05", {"U02": "same_person", "U03": "allowed_alt"})

    assert counts == {"recorded": 2}
    assert conn.committed


def test_main_refused_verdict_returns_2_without_connecting(monkeypatch, capsys):
    monkeypatch.setattr(verdicts, "load_dotenv", lambda *_args: None)
    monkeypatch.setattr(verdicts, "connect", lambda *_args: pytest.fail("connected"))

    assert verdicts.main(["--by", "U09", "--main", "U01", "--same-person", "U01"]) == 2
    assert "main account" in capsys.readouterr().err
