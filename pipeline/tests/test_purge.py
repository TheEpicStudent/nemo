from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from bot.core import audit
from bot.nemo.enforcement import purge

CHANNEL = "C1"
MEMBER = "U9"
PURGE_ID = 7


class Db:
    def __init__(self, channel_id=CHANNEL, member_id=None, wanted=3, state="asked", archived=()):
        self.purge = {"channel_id": channel_id, "member_id": member_id, "wanted": wanted,
                      "asked_by": "UASK", "state": state, "found": None, "error": None,
                      "left": None, "checked": False}
        self.items = {}
        self.archived = list(archived)
        self.audits = []
        self.rows = []

    def execute(self, sql, args=None):
        handlers = {
            purge.CLAIM: self.claim, purge.HELD: self.held, purge.QUEUE: self.queue,
            purge.FOUND: self.found, purge.NEXT: self.next, purge.MARK: self.mark,
            purge.TAKEN: self.taken, purge.PROGRESS: lambda _: [], purge.CHECKING: self.checking,
            purge.DONE_ITEMS: self.done_items, purge.FINISH: self.finish,
            purge.ARCHIVED: self.archive, purge.STRANDED: self.stranded, audit.RECORD: self.audit,
        }
        self.rows = handlers[sql](args) or []
        return self

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return list(self.rows)

    def claim(self, _):
        if self.purge["state"] != "asked":
            return []
        self.purge["state"] = "running"
        p = self.purge
        return [(PURGE_ID, p["channel_id"], p["member_id"], p["wanted"], p["asked_by"])]

    def held(self, _):
        return [(len(self.items),)]

    def put(self, channel_id, ts, thread_ts=None, author_id=None, text=None, reply_count=None,
            state="queued", error=None):
        self.items[(channel_id, ts)] = {"channel_id": channel_id, "ts": ts, "thread_ts": thread_ts,
                                        "author_id": author_id, "text": text,
                                        "reply_count": reply_count, "state": state, "error": error}

    def queue(self, args):
        _, channels, tss, threads, authors, texts, replies = args
        for row in zip(channels, tss, threads, authors, texts, replies):
            if (row[0], row[1]) not in self.items:
                self.put(*row)

    def found(self, args):
        self.purge["found"] = args[0]

    def next(self, _):
        queued = [one for one in self.items.values() if one["state"] == "queued"]
        queued.sort(key=lambda one: (-float(one["thread_ts"] or one["ts"]),
                                     one["thread_ts"] is None, -float(one["ts"])))
        return [(one["channel_id"], one["ts"], one["thread_ts"], one["author_id"], one["text"],
                 one["reply_count"]) for one in queued[:purge.BATCH]]

    def mark(self, args):
        state, error, _, channel_id, ts = args
        self.items[(channel_id, ts)].update(state=state, error=error)

    def taken(self, args):
        _, channel_id, ts, thread_ts, author_id, text, state, error = args
        if (channel_id, ts) in self.items:
            self.items[(channel_id, ts)].update(state=state, error=error)
        else:
            self.put(channel_id, ts, thread_ts, author_id, text, None, state, error)

    def checking(self, _):
        if self.purge["state"] == "running":
            self.purge["state"] = "checking"

    def done_items(self, _):
        return [(one["channel_id"], one["ts"], one["thread_ts"]) for one in self.items.values()]

    def finish(self, args):
        state, error, left, checked, _, _ = args
        if self.purge["state"] not in ("running", "checking"):
            return []
        self.purge.update(state=state, error=error, left=left, checked=checked)
        return [(self.count("deleted"),)]

    def archive(self, args):
        rows = [row for row in self.archived
                if args["channel_id"] is None or row[0] == args["channel_id"]]
        return rows[:args["limit"]]

    def stranded(self, _):
        if self.purge["state"] not in ("running", "checking"):
            return []
        self.purge["state"] = "asked"
        return [(PURGE_ID,)]

    def audit(self, args):
        self.audits.append(args)

    def count(self, state):
        return sum(one["state"] == state for one in self.items.values())

    def state_of(self, ts, channel_id=CHANNEL):
        return self.items[(channel_id, ts)]["state"]


class Slack:
    def __init__(self):
        self.posts = []

    def chat_postMessage(self, **kwargs):
        self.posts.append(kwargs)


def message(ts, text="body a thing", user="U1", **over):
    return {"ts": ts, "user": user, "text": text, **over}


def parent(ts, replies=1, **over):
    return message(ts, thread_ts=ts, reply_count=replies, **over)


def match(channel_id, ts, user=MEMBER, text="said it", **where):
    return {"channel": {"id": channel_id, **where}, "ts": ts, "user": user, "text": text,
            "permalink": f"https://hackclub.slack.com/archives/{channel_id}/p{ts.replace('.', '')}"}


def search_page(matches, pages=1):
    return {"messages": {"matches": matches, "paging": {"pages": pages}}}


@pytest.fixture
def world(monkeypatch):
    state = SimpleNamespace(db=Db(), pages=[], window=[], threads={}, rounds=[], round=[],
                            removed=[], failing=set(), gone=set(), history_calls=[],
                            search_fails=False, allowed=True, asked_keys=[])

    @contextmanager
    def session():
        yield state.db

    def history(channel_id, cursor=None, limit=200, oldest=None, latest=None):
        state.history_calls.append({"cursor": cursor, "oldest": oldest, "latest": latest})
        if oldest is not None or latest is not None:
            return {"messages": state.window}
        return state.pages.pop(0) if state.pages else {"messages": []}

    def replies(channel_id, ts, cursor=None, limit=200):
        pending = state.threads.get(ts) or []
        return {"messages": [message(ts)] + (pending.pop(0) if pending else [])}

    def search(query, page=1, count=100):
        if state.search_fails:
            raise RuntimeError("search is down")
        if page == 1:
            state.round = state.rounds.pop(0) if state.rounds else []
        return state.round[page - 1] if page <= len(state.round) else search_page([], len(state.round))

    def remove(_client, channel_id, ts):
        if ts in state.failing:
            raise RuntimeError("cant_delete_message")
        if ts in state.gone:
            raise RuntimeError("message_not_found")
        state.removed.append((channel_id, ts))

    def may(conn, user_id, key, case_id=None):
        state.asked_keys.append((user_id, key))
        return (True, None) if state.allowed else (False, "Community manager only")

    monkeypatch.setattr(purge, "session", session)
    monkeypatch.setattr(purge.access, "may", may)
    monkeypatch.setattr(purge.privileged, "history", history)
    monkeypatch.setattr(purge.privileged, "replies", replies)
    monkeypatch.setattr(purge.privileged, "search", search)
    monkeypatch.setattr(purge.guard_actions, "remove", remove)
    monkeypatch.setattr(purge.channel, "internal_log_channel", lambda: "CLOG")
    monkeypatch.setattr(purge.channel, "app_url", lambda path: f"https://fd.test{path}")
    monkeypatch.setattr(purge.channel, "member_url", lambda user_id: f"https://fd.test/m/{user_id}")
    monkeypatch.setattr(purge, "CHECK_DELAY_SECONDS", 0)
    return state


def test_a_purge_that_is_not_claimed_does_nothing(world):
    world.db = Db(state="done")

    assert purge.run(Slack(), PURGE_ID) == 0
    assert world.removed == []
    assert world.db.audits == []


def test_a_purge_whose_asker_lost_the_right_deletes_nothing(world):
    world.pages = [{"messages": [message("2"), message("1")]}]
    world.allowed = False

    assert purge.run(Slack(), PURGE_ID) == 0
    assert world.removed == []
    assert world.db.purge["state"] == "failed"
    assert "<@UASK> may no longer purge" in world.db.purge["error"]


def test_each_kind_of_purge_asks_for_its_own_right(world):
    world.pages = [{"messages": [message("1")]}]
    purge.run(Slack(), PURGE_ID)
    world.db = Db(channel_id=None, member_id=MEMBER, wanted=None)
    purge.run(Slack(), PURGE_ID)

    assert world.asked_keys == [("UASK", "channel.purge"), ("UASK", "member.purge")]


def test_the_newest_are_taken_down_in_order(world):
    world.pages = [{"messages": [message("3"), message("2"), message("1")]}]

    assert purge.run(Slack(), PURGE_ID) == 3
    assert world.removed == [(CHANNEL, "3"), (CHANNEL, "2"), (CHANNEL, "1")]
    assert world.db.purge["state"] == "done"
    assert world.db.purge["found"] == 3


def test_what_was_taken_down_is_kept_with_its_words(world):
    world.pages = [{"messages": [message("3", "the thing said")]}]
    purge.run(Slack(), PURGE_ID)

    kept = world.db.items[(CHANNEL, "3")]
    assert (kept["text"], kept["author_id"], kept["state"]) == ("the thing said", "U1", "deleted")


def test_it_stops_at_what_was_asked_for(world):
    world.pages = [{"messages": [message(str(n)) for n in range(9, 0, -1)]}]
    purge.run(Slack(), PURGE_ID)

    assert world.removed == [(CHANNEL, "9"), (CHANNEL, "8"), (CHANNEL, "7")]


def test_a_join_notice_is_not_counted(world):
    world.pages = [{"messages": [message("4"), message("3", subtype="channel_join"),
                                 message("2"), message("1")]}]
    purge.run(Slack(), PURGE_ID)

    assert world.removed == [(CHANNEL, "4"), (CHANNEL, "2"), (CHANNEL, "1")]


def test_it_pages_until_it_has_enough(world):
    world.pages = [
        {"messages": [message("5")], "response_metadata": {"next_cursor": "more"}},
        {"messages": [message("4"), message("3")]},
    ]
    purge.run(Slack(), PURGE_ID)

    assert world.history_calls[1]["cursor"] == "more"
    assert len(world.removed) == 3


def test_every_message_goes_when_no_count_is_given(world):
    world.db = Db(wanted=None)
    world.pages = [{"messages": [message(str(n)) for n in range(9, 0, -1)]}]

    assert purge.run(Slack(), PURGE_ID) == 9


def test_the_replies_go_before_the_parent_and_late_replies_are_caught(world):
    world.pages = [{"messages": [parent("3", replies=1)]}]
    world.threads = {"3": [[message("3.1")], [message("3.2")]]}
    purge.run(Slack(), PURGE_ID)

    assert world.removed == [(CHANNEL, "3.1"), (CHANNEL, "3.2"), (CHANNEL, "3")]
    assert world.db.items[(CHANNEL, "3.1")]["thread_ts"] == "3"
    assert world.db.items[(CHANNEL, "3")]["thread_ts"] is None


def test_a_message_already_gone_is_not_counted(world):
    world.pages = [{"messages": [message("2"), message("1")]}]
    world.gone = {"1"}

    assert purge.run(Slack(), PURGE_ID) == 1
    assert world.db.state_of("1") == "gone"


def test_a_delete_that_fails_is_kept_and_the_rest_go_on(world):
    world.pages = [{"messages": [message("3"), message("2"), message("1")]}]
    world.failing = {"2"}

    assert purge.run(Slack(), PURGE_ID) == 2
    assert world.db.state_of("2") == "failed"
    assert "cant_delete_message" in world.db.items[(CHANNEL, "2")]["error"]
    assert world.db.purge["state"] == "done"


def test_too_many_failures_in_a_row_stops_it(world, monkeypatch):
    monkeypatch.setattr(purge, "FAILURES_IN_A_ROW", 2)
    world.pages = [{"messages": [message("3"), message("2"), message("1")]}]
    world.failing = {"3", "2", "1"}
    purge.run(Slack(), PURGE_ID)

    assert world.db.purge["state"] == "failed"
    assert "failed in a row" in world.db.purge["error"]


def test_more_than_the_cap_stops_it(world, monkeypatch):
    monkeypatch.setattr(purge, "CAP", 2)
    world.pages = [{"messages": [parent("3")]}]
    world.threads = {"3": [[message("3.1"), message("3.2"), message("3.3")]]}
    purge.run(Slack(), PURGE_ID)

    assert world.db.purge["state"] == "failed"
    assert "more than 2" in world.db.purge["error"]


def test_the_check_takes_down_what_is_still_there(world):
    world.pages = [{"messages": [message("3"), message("2"), message("1")]}]
    world.window = [message("2"), message("9", subtype="channel_join")]
    purge.run(Slack(), PURGE_ID)

    assert world.history_calls[-1]["oldest"] == "1"
    assert world.history_calls[-1]["latest"] == "3"
    assert world.removed.count((CHANNEL, "2")) == 2
    assert world.db.purge["left"] == 0
    assert world.db.purge["checked"] is True


def test_what_the_check_cannot_take_down_is_counted(world, monkeypatch):
    world.pages = [{"messages": [message("2"), message("1")]}]
    world.window = [message("2")]

    def fail_on_the_second_try(_client, channel_id, ts):
        if (channel_id, ts) in world.removed:
            raise RuntimeError("cant_delete_message")
        world.removed.append((channel_id, ts))

    monkeypatch.setattr(purge.guard_actions, "remove", fail_on_the_second_try)
    purge.run(Slack(), PURGE_ID)

    assert world.db.purge["left"] == 1


def test_a_member_is_purged_from_the_archive_and_search(world):
    world.db = Db(channel_id=None, member_id=MEMBER, wanted=None,
                  archived=[("C1", "5.0", None), ("C2", "4.0", "3.9")])
    world.rounds = [[search_page([
        match("C3", "6.0", text="from search"),
        match("C1", "5.0", text="the words"),
        match("D1", "7.0", is_im=True),
        match("C4", "8.0", user="USOMEONE"),
    ])]]

    assert purge.run(Slack(), PURGE_ID) == 3
    assert world.removed == [("C3", "6.0"), ("C1", "5.0"), ("C2", "4.0")]
    assert world.db.items[("C1", "5.0")]["text"] == "the words"
    assert world.db.items[("C2", "4.0")]["thread_ts"] == "3.9"


def test_a_member_purge_in_one_channel_stays_there(world):
    world.db = Db(channel_id="C1", member_id=MEMBER, wanted=None,
                  archived=[("C1", "5.0", None), ("C2", "4.0", None)])
    world.rounds = [[search_page([match("C1", "6.0"), match("C3", "7.0")])]]
    purge.run(Slack(), PURGE_ID)

    assert world.removed == [("C1", "6.0"), ("C1", "5.0")]


def test_a_member_purge_takes_only_the_last_few_asked_for(world):
    world.db = Db(channel_id=None, member_id=MEMBER, wanted=2,
                  archived=[("C1", "5.0", None), ("C2", "4.0", None), ("C2", "3.0", None)])
    purge.run(Slack(), PURGE_ID)

    assert world.removed == [("C1", "5.0"), ("C2", "4.0")]


def test_the_member_check_takes_what_search_still_finds(world):
    world.db = Db(channel_id=None, member_id=MEMBER, wanted=None,
                  archived=[("C1", "5.0", None)])
    world.rounds = [[search_page([])], [search_page([match("C2", "6.0", text="posted late")])]]
    purge.run(Slack(), PURGE_ID)

    assert world.removed == [("C1", "5.0"), ("C2", "6.0")]
    assert world.db.items[("C2", "6.0")]["text"] == "posted late"
    assert world.db.purge["left"] == 0


def test_a_search_failure_leaves_the_archive_to_carry_on(world):
    world.db = Db(channel_id=None, member_id=MEMBER, wanted=None,
                  archived=[("C1", "5.0", None)])
    world.search_fails = True
    purge.run(Slack(), PURGE_ID)

    assert world.removed == [("C1", "5.0")]
    assert world.db.purge["state"] == "done"
    assert world.db.purge["left"] is None
    assert world.db.purge["error"] == "the check could not run: search is down"


def test_a_restart_carries_on_without_collecting_again(world):
    world.db.put(CHANNEL, "2", author_id="U1", text="queued before the restart")
    world.db.put(CHANNEL, "1", state="deleted")
    purge.run(Slack(), PURGE_ID)

    assert [call for call in world.history_calls if call["oldest"] is None] == []
    assert world.removed[0] == (CHANNEL, "2")


def test_a_purge_cut_off_by_a_restart_goes_again(world):
    world.db = Db(state="running")

    assert purge.requeue_stranded(world.db) == [PURGE_ID]
    assert world.db.purge["state"] == "asked"


def test_how_it_went_is_posted_and_audited(world):
    world.pages = [{"messages": [message("2"), message("1")]}]
    slack = Slack()
    purge.run(slack, PURGE_ID)

    [post] = slack.posts
    assert post["channel"] == "CLOG"
    assert "Purge 7: 2 messages deleted in <#C1>, 0 left after the check." in post["text"]
    assert "Asked by <@UASK>" in post["text"]
    assert "https://fd.test/fd/channels/C1/purges/7" in post["text"]
    [row] = world.db.audits
    assert (row[2], row[3], row[4]) == ("channel_purge", PURGE_ID, "performed")


def test_a_member_purge_is_audited_against_the_member(world):
    world.db = Db(channel_id=None, member_id=MEMBER, wanted=None, archived=[("C1", "5.0", None)])
    slack = Slack()
    purge.run(slack, PURGE_ID)

    [row] = world.db.audits
    assert (row[2], row[4], row[8]) == ("member_purge", "performed", MEMBER)
    assert "from <@U9> in every channel" in slack.posts[0]["text"]
