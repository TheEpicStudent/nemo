from checks import audit_actions as check
from ingest import audit_logs_pull as pull
from lib import audit_actions


def test_catalogue_action_category_is_known():
    catalogue = audit_actions.catalogue()
    names = set(audit_actions.categories(catalogue))
    for action, one in catalogue["actions"].items():
        assert one["category"] in names, action
        assert one["label"] and one["sentence"], action


def test_catalogue_every_category_has_action():
    catalogue = audit_actions.catalogue()
    used = {one["category"] for one in catalogue["actions"].values()}
    assert used == set(audit_actions.categories(catalogue))


def test_catalogue_sentence_contains_only_known_placeholders():
    for action, one in audit_actions.catalogue()["actions"].items():
        stripped = one["sentence"]
        for placeholder in audit_actions.PLACEHOLDERS:
            stripped = stripped.replace(placeholder, "")
        assert "{" not in stripped and "}" not in stripped, action


def test_catalogue_label_and_sentence_contain_no_em_dash():
    for action, one in audit_actions.catalogue()["actions"].items():
        assert "—" not in one["label"] + one["sentence"], action


def test_unknown_pulled_actions_returns_empty_list():
    action_names = set(pull.LOGIN_ACTIONS) | set(pull.CHANNEL_MEMBERSHIP_ACTIONS) | set(pull.IDENTITY_ACTIONS)
    assert audit_actions.unknown(action_names) == []


def test_entry_unknown_action_falls_back_to_action_name():
    entry = audit_actions.entry("brand_new_thing")

    assert entry == {"category": None, "label": "brand new thing", "sentence": "{actor}: brand new thing"}
    assert audit_actions.entry("user_login")["label"] == "Signed in"


def test_unknown_duplicate_missing_action_is_listed_once():
    assert audit_actions.unknown(["user_login", "brand_new_thing", "brand_new_thing", None]) == ["brand_new_thing"]


class Conn:
    def __init__(self, actions):
        self.actions = actions

    def execute(self, _sql, _params=None):
        return self

    def fetchall(self):
        return [(one,) for one in self.actions]


def test_catalogued_check_with_missing_action_warns():
    assertion, status, observed, _expected = check.catalogued(Conn(["user_login", "brand_new_thing"]))

    assert status == "warn"
    assert "brand_new_thing" in observed
    assert check.catalogued(Conn(["user_login"]))[1] == "pass"
