from bot.nemo import case_actions


class Conn:
    def __init__(self, previous="spam", changed=True):
        self.previous = previous
        self.changed = changed
        self.executed = []

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        return self

    def fetchone(self):
        return (self.previous,) if self.changed else None


def test_set_category_replaces_existing_category_and_audits_both_values():
    conn = Conn(previous="spam")

    assert case_actions.set_category(conn, 49, "harassment", "UMOD") is True

    assert "IS DISTINCT FROM" in conn.executed[0][0]
    assert conn.executed[0][1] == ("harassment", 49, 49, "harassment")
    assert len(conn.executed) == 2


def test_set_category_to_the_current_category_changes_nothing():
    conn = Conn(changed=False)

    assert case_actions.set_category(conn, 49, "spam", "UMOD") is False
    assert len(conn.executed) == 1
