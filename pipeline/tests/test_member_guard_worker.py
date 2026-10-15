import inspect

from bot.nemo import loop


class _conn_context:
    def __enter__(self):
        return object()

    def __exit__(self, *failure):
        return False


def guard(guard_id, kind="shush"):
    return {"id": guard_id, "kind": kind, "subject_id": "U1", "channel_id": None,
            "reason": "spam", "expires_at": None}


def install_fakes(monkeypatch, pending=(), lifting=(), failing=(), lifted=()):
    enforced_ids, released = [], []

    def fake_take_up(client, one):
        if one["id"] in failing:
            raise RuntimeError("slack is down")
        enforced_ids.append(one["id"])

    monkeypatch.setattr(loop, "session", lambda: _conn_context())
    monkeypatch.setattr(loop.memberguards, "refresh", lambda conn: 0)
    monkeypatch.setattr(loop.memberguards, "unenforced", lambda conn: list(pending))
    monkeypatch.setattr(loop.memberguards, "still_lifting", lambda conn: list(lifting))
    monkeypatch.setattr(loop.memberguards, "lifted_not_notified", lambda conn, within: list(lifted))
    monkeypatch.setattr(loop.sweep, "release_lifted",
                        lambda client, one: released.append(("lifted", one["id"])))
    monkeypatch.setattr(loop, "take_up", fake_take_up)
    monkeypatch.setattr(loop.sweep, "release_now",
                        lambda client, one: released.append(one["id"]))
    return enforced_ids, released


def test_a_flush_takes_up_what_is_pending_and_finishes_what_is_lifting(monkeypatch):
    enforced_ids, released = install_fakes(monkeypatch, pending=[guard(1), guard(2)],
                                           lifting=[guard(3, "deactivation")])

    loop.flush_pending(object())

    assert enforced_ids == [1, 2]
    assert released == [3]


def test_one_guard_failing_does_not_stop_the_rest(monkeypatch):
    enforced_ids, _released = install_fakes(monkeypatch, pending=[guard(1), guard(2)], failing={1})

    loop.flush_pending(object())

    assert enforced_ids == [2]


def test_a_flush_never_asks_the_worker_to_go_straight_again(monkeypatch):
    install_fakes(monkeypatch, pending=[guard(1)])

    assert not loop.flush_pending(object())


def test_the_sweep_leaves_member_guards_to_the_worker():
    once_source = inspect.getsource(loop.once)

    assert "unenforced" not in once_source
    assert "take_up" not in once_source
    assert "sweep_lifting" not in once_source


def test_a_member_guard_notification_wakes_the_worker_instead_of_a_thread():
    start_source = inspect.getsource(loop.start)

    assert 'loops.draining(f"{NAME}-member-guards"' in start_source
    assert "target=flush_pending" not in start_source


def test_flush_pending_releases_guards_lifted_in_the_dashboard(monkeypatch):
    _enforced_ids, released = install_fakes(monkeypatch, lifting=[guard(3, "deactivation")],
                                            lifted=[guard(4), guard(5, "channel_ban")])

    loop.flush_pending(object())

    assert released == [3, ("lifted", 4), ("lifted", 5)]

