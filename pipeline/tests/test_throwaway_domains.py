import contextlib
import pathlib

from ingest import throwaway_domains as throwaway
from jobs import audit_worker


def test_domains_in_comments_and_invalid_lines_are_skipped():
    text = "# disposable\n0-mail.com\nMiniTTS.net  \n@yzcalo.com\nnot a domain\n\nlocalhost\n"

    assert throwaway.domains_in(text) == {"0-mail.com", "minitts.net", "yzcalo.com"}


def test_curated_includes_known_domain_and_null_setting_returns_empty_set():
    assert "e.izie.top" in throwaway.curated()
    assert throwaway.curated({"throwaway_domains": None}) == set()


def test_merged_domain_in_both_sources_is_marked_curated():
    rows = throwaway.merged({"minitts.net", "e.izie.top"}, {"e.izie.top"})

    assert rows == {"minitts.net": "list", "e.izie.top": "curated"}


class Conn:
    def __init__(self):
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return self

    def commit(self):
        self.executed.append(("commit", None))


@contextlib.contextmanager
def fake_ingest_run(*_args, **_kwargs):
    yield type("Counts", (), {"rows_in": 0})()


def test_run_loads_list_then_drops_removed_domains(tmp_path, monkeypatch):
    list_file = tmp_path / "list.conf"
    list_file.write_text("\n".join(f"temp{n}.example" for n in range(throwaway.MIN_LIST_SIZE)) + "\n")
    monkeypatch.setattr(throwaway, "download_cached", lambda *_args: list_file)
    monkeypatch.setattr(throwaway, "ingest_run", fake_ingest_run)
    conn = Conn()

    assert throwaway.run(conn) == throwaway.MIN_LIST_SIZE + len(throwaway.curated())
    load, drop, commit = conn.executed
    assert load[0] == throwaway.LOAD_SQL and "e.izie.top" in load[1][0]
    assert load[1][1][load[1][0].index("e.izie.top")] == "curated"
    assert drop == (throwaway.DROP_SQL, (load[1][0],))
    assert commit[0] == "commit"


def test_run_list_below_min_list_size_executes_no_sql(tmp_path, monkeypatch, capsys):
    list_file = tmp_path / "list.conf"
    list_file.write_text("only.example\n")
    monkeypatch.setattr(throwaway, "download_cached", lambda *_args: list_file)
    conn = Conn()

    assert throwaway.run(conn) == 0
    assert conn.executed == []
    assert "keeping the ones already loaded" in capsys.readouterr().out


def test_audit_worker_throwaway_domains_lane_runs_daily():
    lane = next(one for one in audit_worker.LANES if one[0] == "throwaway_domains")

    assert lane[1] is throwaway.run
    assert lane[3] == 86400 and lane[4] is False


def test_throwaway_domain_migration_defines_primary_key_and_lowercase_check():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0218_throwaway_domain.sql").read_text()

    assert "domain       text        PRIMARY KEY" in sql
    assert "CHECK (source IN ('list', 'curated'))" in sql
    assert "CHECK (domain = lower(domain))" in sql
    assert "GRANT SELECT ON fd.throwaway_domain TO rails_app" in sql
