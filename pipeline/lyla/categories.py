from lyla.mapping import CATEGORY_CODES, CATEGORY_KEYS, NEMO_NAMED_CODES

LYLA_CATEGORIES = "SELECT code, name, active FROM infraction_categories"

NEMO_CATEGORIES = "SELECT key, label, retired_at FROM fd.infraction_categories ORDER BY position, key"

ADD = """
INSERT INTO infraction_categories (code, name, active, sort_order)
VALUES (%s, %s, %s, %s)
ON CONFLICT (code) DO NOTHING
"""

RENAME = "UPDATE infraction_categories SET name = %s, active = %s WHERE code = %s"


class Categories:
    def __init__(self, lyla_rows, nemo_rows):
        self.lyla_names = {code: name for code, name, _active in lyla_rows}
        self.lyla_active = {code: active for code, _name, active in lyla_rows}
        self.nemo_labels = {key: label for key, label, _retired in nemo_rows}
        self.nemo_retired = {key: retired is not None for key, _label, retired in nemo_rows}

    def key_for(self, code):
        if code is None:
            return None
        if code in CATEGORY_KEYS:
            return CATEGORY_KEYS[code]
        name = self.lyla_names.get(code)
        return next((key for key, label in self.nemo_labels.items() if label == name), None)

    def code_for(self, key):
        if key is None:
            return None
        if key in CATEGORY_CODES:
            return CATEGORY_CODES[key]
        label = self.nemo_labels.get(key)
        return next((code for code, name in self.lyla_names.items() if name == label), None)

    def wanted(self):
        rows = []
        next_code = max([*self.lyla_names, *CATEGORY_KEYS], default=-1) + 1
        for key, label in self.nemo_labels.items():
            code = CATEGORY_CODES.get(key)
            active = not self.nemo_retired.get(key)
            if code is None:
                code = self.code_for(key)
                if code is None:
                    code, next_code = next_code, next_code + 1
                    rows.append(("add", code, label, active))
                continue
            if code not in self.lyla_names:
                rows.append(("add", code, label, active))
            elif code in NEMO_NAMED_CODES and (self.lyla_names[code] != label
                                               or self.lyla_active.get(code) != active):
                rows.append(("rename", code, label, active))
        return rows


def load(conn, lyla):
    return Categories(lyla.execute(LYLA_CATEGORIES).fetchall(),
                      conn.execute(NEMO_CATEGORIES).fetchall())


def mirror(conn, lyla):
    categories = load(conn, lyla)
    changes = categories.wanted()
    for kind, code, label, active in changes:
        if kind == "add":
            lyla.execute(ADD, (code, label, active, code))
        else:
            lyla.execute(RENAME, (label, active, code))
    lyla.commit()
    return changes
