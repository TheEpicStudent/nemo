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

    def fake_enforce(client, one):
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
    monkeypatch.setattr(loop, "enforce_guard", fake_enforce)
    monkeypatch.setattr(loop.sweep, "release_now",
                        lambda client, one: released.append(one["id"]))
    return enforced_ids, released


def test_apply_pending_guards_enforces_pending_and_releases_lifting(monkeypatch):
    enforced_ids, released = install_fakes(monkeypatch, pending=[guard(1), guard(2)],
                                           lifting=[guard(3, "deactivation")])

    loop.apply_pending_guards(object())

    assert enforced_ids == [1, 2]
    assert released == [3]


def test_apply_pending_guards_failing_guard_does_not_block_others(monkeypatch):
    enforced_ids, _released = install_fakes(monkeypatch, pending=[guard(1), guard(2)], failing={1})

    loop.apply_pending_guards(object())

    assert enforced_ids == [2]


def test_apply_pending_guards_does_not_request_immediate_rerun(monkeypatch):
    install_fakes(monkeypatch, pending=[guard(1)])

    assert not loop.apply_pending_guards(object())


def test_sweep_once_source_excludes_member_guard_enforcement():
    once_source = inspect.getsource(loop.sweep_once)

    assert "unenforced" not in once_source
    assert "enforce_guard" not in once_source
    assert "sweep_lifting" not in once_source


def test_start_source_runs_member_guards_on_wake_not_thread():
    start_source = inspect.getsource(loop.start)

    assert 'loops.run_on_wake(f"{NAME}-member-guards"' in start_source
    assert "target=apply_pending_guards" not in start_source


def test_apply_pending_guards_releases_lifting_and_lifted_guards(monkeypatch):
    _enforced_ids, released = install_fakes(monkeypatch, lifting=[guard(3, "deactivation")],
                                            lifted=[guard(4), guard(5, "channel_ban")])

    loop.apply_pending_guards(object())

    assert released == [3, ("lifted", 4), ("lifted", 5)]

