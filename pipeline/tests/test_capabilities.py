import yaml

from bot.core import access
from lib import capabilities
from lib.paths import PANELS_FILE

TABLE = capabilities.table()
PANELS = yaml.safe_load(PANELS_FILE.read_text())["panels"]


def test_consistency_errors_for_table_is_empty():
    assert capabilities.consistency_errors(TABLE) == []


def test_capabilities_every_entry_declares_known_area():
    areas = set(TABLE["areas"])
    for key, one in capabilities.capabilities(TABLE).items():
        assert one["area"] in areas, f"{key} declares area {one['area']!r}"


def test_roles_superadmin_lists_no_capabilities():
    for name, one in capabilities.roles(TABLE).items():
        if one.get("everything"):
            assert not one.get("capabilities"), f"{name} both is superadmin and lists capabilities"


def test_role_capability_rows_name_known_capabilities():
    known = set(capabilities.capabilities(TABLE))
    for role, key in capabilities.role_capability_rows(TABLE):
        assert key in known, f"{role} holds {key}, which is not a capability"


def test_capabilities_record_scope_is_in_declared_set():
    allowed = set(TABLE["record_scopes"])
    for key, one in capabilities.capabilities(TABLE).items():
        scope = one.get("record_scope")
        assert scope is None or scope in allowed, f"{key} declares scope {scope!r}"


def test_supported_scopes_include_every_declared_record_scope():
    for scope in TABLE["record_scopes"]:
        assert scope in access.SUPPORTED_SCOPES, f"nemo does not weigh the {scope} scope"


def test_in_scope_unsupported_scope_returns_refusal():
    allowed, refusal = access.in_scope({"label": "Do a thing", "record_scope": "assigned"})
    assert allowed is False
    assert refusal == "You do not have permission to do a thing."


def test_in_scope_unscoped_capability_returns_allowed():
    assert access.in_scope({"label": "Do a thing", "record_scope": None}) == (True, None)


def test_panels_needs_is_known_capability_or_none():
    known = set(capabilities.capabilities(TABLE))
    for name, one in PANELS.items():
        required = one.get("needs")
        assert required is None or required in known, f"panel {name} needs {required!r}, not a capability"


def test_capabilities_locked_matches_fixed_list():
    locked = [k for k, one in capabilities.capabilities(TABLE).items() if one.get("locked")]
    assert locked == [
        "case.read", "case.open", "case.categorise", "case.tag", "case.note", "case.people",
        "case.chat", "case.reply", "case.act", "case.resolve",
        "case.reverse", "case.reopen", "thread.guard", "member.note", "member.guard",
        "member.deactivate", "member.purge", "member.links", "link.verdict", "identity.read",
        "audit.read", "channel.share", "channel.guard", "channel.purge", "message.show",
        "engine.manage", "access.grant", "app.flip", "app.configure",
    ], locked


def test_roles_everything_flag_is_only_community_manager():
    superusers = [n for n, one in capabilities.roles(TABLE).items() if one.get("everything")]
    assert superusers == ["community_manager"], superusers
