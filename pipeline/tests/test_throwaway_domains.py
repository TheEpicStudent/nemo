import contextlib
import pathlib

from ingest import throwaway_domains as throwaway
from jobs import audit_worker


def test_the_list_reads_one_domain_a_line_and_skips_comments_and_junk():
    text = "# disposable\n0-mail.com\nMiniTTS.net  \n@yzcalo.com\nnot a domain\n\nlocalhost\n"

    assert throwaway.domains_in(text) == {"0-mail.com", "minitts.net", "yzcalo.com"}


def test_the_ring_domain_is_curated_because_the_public_list_misses_it():
    assert "e.izie.top" in throwaway.curated()
    assert throwaway.curated({"throwaway_domains": None}) == set()


def test_a_curated_domain_wins_over_the_same_domain_on_the_list():
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


def test_a_refresh_loads_the_list_then_drops_what_left_it(tmp_path, monkeypatch):
    listed = tmp_path / "list.conf"
    listed.write_text("\n".join(f"temp{n}.example" for n in range(throwaway.SMALLEST_LIST)) + "\n")
    monkeypatch.setattr(throwaway, "download_cached", lambda *_args: listed)
    monkeypatch.setattr(throwaway, "ingest_run", fake_ingest_run)
    conn = Conn()

    assert throwaway.run(conn) == throwaway.SMALLEST_LIST + len(throwaway.curated())
    load, drop, commit = conn.executed
    assert load[0] == throwaway.LOAD_SQL and "e.izie.top" in load[1][0]
    assert load[1][1][load[1][0].index("e.izie.top")] == "curated"
    assert drop == (throwaway.DROP_SQL, (load[1][0],))
    assert commit[0] == "commit"


def test_a_list_that_comes_back_short_keeps_the_domains_already_loaded(tmp_path, monkeypatch, capsys):
    listed = tmp_path / "list.conf"
    listed.write_text("only.example\n")
    monkeypatch.setattr(throwaway, "download_cached", lambda *_args: listed)
    conn = Conn()

    assert throwaway.run(conn) == 0
    assert conn.executed == []
    assert "keeping the ones already loaded" in capsys.readouterr().out


def test_the_audit_worker_refreshes_the_list_once_a_day():
    lane = next(one for one in audit_worker.LANES if one[0] == "throwaway_domains")

    assert lane[1] is throwaway.run
    assert lane[3] == 86400 and lane[4] is False


def test_the_table_keeps_one_lowercase_row_per_domain():
    sql = (pathlib.Path(__file__).parents[2] / "db" / "migrations" / "0218_throwaway_domain.sql").read_text()

    assert "domain       text        PRIMARY KEY" in sql
    assert "CHECK (source IN ('list', 'curated'))" in sql
    assert "CHECK (domain = lower(domain))" in sql
    assert "GRANT SELECT ON fd.throwaway_domain TO rails_app" in sql
