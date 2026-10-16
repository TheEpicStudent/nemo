from checks import roles


class Cluster:
    def __init__(self, present, counts=0):
        self.present = present
        self.counts = counts

    def execute(self, sql, params=None):
        self.last = [(name,) for name in self.present] if "pg_roles" in sql else [(self.counts,)]
        return self

    def fetchall(self):
        return self.last

    def fetchone(self):
        return self.last[0]


def named(results):
    return {assertion: (status, observed) for assertion, status, observed, _ in results}


def test_deployment_mode_declared_with_expected_roles_reports_separated_mode():
    results = named(check(conn) for check in roles.CHECKS for conn in [Cluster(roles.EXPECTED_ROLES)])
    status, observed = results["the deployment mode is declared"]
    assert status == "pass"
    assert roles.SEPARATED_MODE in observed


def test_deployment_mode_declared_without_roles_passes_with_shared_mode():
    conn = Cluster([])
    assertion, status, observed, _ = roles.deployment_mode_declared(conn)
    assert (assertion, status) == ("the deployment mode is declared", "pass")
    assert roles.SHARED_MODE in observed
    assert "capability checks" in observed


def test_separation_checks_with_shared_login_are_skipped():
    for check in roles.CHECKS[1:]:
        assertion, status, observed, _ = check(Cluster(["rails_app"]))
        assert status == "skipped", assertion
        assert roles.SHARED_MODE in observed


def test_separation_checks_with_roles_present_and_nonzero_counts_fail():
    for check in roles.CHECKS[1:]:
        assertion, status, _, _ = check(Cluster(roles.EXPECTED_ROLES, counts=3))
        assert status == "fail", assertion


def test_severity_of_skipped_and_pass_is_info_and_fail_is_error():
    assert roles.severity_of("skipped") == "info"
    assert roles.severity_of("pass") == "info"
    assert roles.severity_of("fail") == "error"
