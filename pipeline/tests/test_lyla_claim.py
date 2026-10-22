from lyla import claim, status


class Conn:
    def __init__(self, link=None, claimed=False, imported=True):
        self.link = link
        self.claimed = claimed
        self.imported = imported

    def execute(self, sql, args=None):
        if "fd.app_settings" in sql:
            return Rows([(self.link,)] if self.link else [])
        if sql == status.IMPORTED:
            return Rows([(1,)] if self.imported else [])
        return Rows([(1,)] if self.claimed else [])


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


def test_waiting_with_link_on_and_no_lyla_thread():
    assert claim.waiting(Conn(link="on"), 5010)


def test_waiting_with_link_on_and_a_lyla_thread_is_false():
    assert not claim.waiting(Conn(link="on", claimed=True), 5010)


def test_waiting_with_link_off_is_false():
    assert not claim.waiting(Conn(link="off"), 5010)
    assert not claim.waiting(Conn(), 5010)


def test_waiting_before_the_import_is_false():
    assert not claim.waiting(Conn(link="on", imported=False), 5010)
