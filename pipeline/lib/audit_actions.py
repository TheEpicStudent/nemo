import yaml

from lib.paths import AUDIT_ACTIONS_FILE

PLACEHOLDERS = ("{actor}", "{entity}")


def catalogue():
    return yaml.safe_load(AUDIT_ACTIONS_FILE.read_text())


def categories(catalogue_data=None):
    return (catalogue_data or catalogue())["categories"]


def entry(action, catalogue_data=None):
    action_entry = (catalogue_data or catalogue())["actions"].get(action)
    if action_entry:
        return action_entry
    label = str(action or "").replace("_", " ").replace(".", " ")
    return {"category": None, "label": label, "sentence": "{actor}: " + label}


def unknown(actions, catalogue_data=None):
    known = (catalogue_data or catalogue())["actions"]
    return sorted({one for one in actions if one and one not in known})


def slim_actions(catalogue_data=None):
    return sorted(name for name, one in (catalogue_data or catalogue())["actions"].items() if one.get("slim"))
