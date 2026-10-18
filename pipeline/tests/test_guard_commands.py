import pytest

from bot.nemo import channelguards, channels, command, guard_commands

CHANNEL = "C1LOUNGE"
MOD = "UMOD"
MEMBER = "U1MEMBER"
BOT = "U2BOT"
HERE = CHANNEL


class Store:
    def __init__(self):
        self.guards = {}
        self.calls = []
        self.inside = True
        self.joined = True
        self.next_id = 1

    def row(self, channel_id, kind):
        guard = self.guards.get((channel_id, kind))
        return (guard["id"], guard["settings"]) if guard else None


@pytest.fixture
def store(monkeypatch):
    state = Store()

    def live_guard_settings(conn, channel_id, kind):
        return state.row(channel_id, kind)

    def open_guard(conn, channel_id, by, case_id=None, kind=channelguards.BOT_ALLOWLIST, settings=None):
        guard = {"id": state.next_id, "settings": dict(settings or {}), "allowed": []}
        state.next_id += 1
        state.guards[(channel_id, kind)] = guard
        state.calls.append(("open", kind, guard["settings"], by))
        return guard["id"]

    def tune(conn, guard_id, settings, by):
        for guard in state.guards.values():
            if guard["id"] == guard_id:
                guard["settings"].update(settings)
        state.calls.append(("tune", settings, by))

    def restore_allows(conn, guard_id, channel_id, kind, by):
        state.calls.append(("restore", kind))
        return []

    def lift(conn, guard_id, by):
        for key, guard in list(state.guards.items()):
            if guard["id"] == guard_id:
                del state.guards[key]
        state.calls.append(("lift", guard_id, by))

    def guard_by_id(guard_id):
        return next(one for one in state.guards.values() if one["id"] == guard_id)

    def allowed(conn, guard_id):
        return [(subject_id, label, MOD, None) for subject_id, label in guard_by_id(guard_id)["allowed"]]

    def allow(conn, guard_id, subject_id, by, label=None):
        guard_by_id(guard_id)["allowed"].append((subject_id, label))
        state.calls.append(("allow", subject_id, by))
        return subject_id

    def disallow(conn, guard_id, subject_id, by):
        guard = guard_by_id(guard_id)
        before = list(guard["allowed"])
        guard["allowed"] = [one for one in before if one[0] != subject_id]
        state.calls.append(("disallow", subject_id, by))
        return subject_id if len(before) != len(guard["allowed"]) else None

    monkeypatch.setattr(channelguards, "live_guard_settings", live_guard_settings)
    monkeypatch.setattr(channelguards, "open_guard", open_guard)
    monkeypatch.setattr(channelguards, "tune", tune)
    monkeypatch.setattr(channelguards, "restore_allows", restore_allows)
    monkeypatch.setattr(channelguards, "lift", lift)
    monkeypatch.setattr(channelguards, "allowed", allowed)
    monkeypatch.setattr(channelguards, "allow", allow)
    monkeypatch.setattr(channelguards, "disallow", disallow)
    monkeypatch.setattr(channels, "is_inside", lambda conn, channel_id: state.inside)
    monkeypatch.setattr(channels, "join", lambda client, conn, channel_id, by=None, verb="joined": state.joined)
    return state


def run(verb, text="", subject=None, channel_id=CHANNEL):
    return guard_commands.run(None, None, verb, channel_id, text, subject, MOD)


def test_run_without_channel_returns_channel_usage(store):
    assert run(guard_commands.READONLY, channel_id=None) == guard_commands.CHANNEL_USAGE[guard_commands.READONLY]


def test_run_in_direct_message_returns_channel_usage(store):
    assert run(guard_commands.BOT_ALLOW, "on", channel_id="D1DM") == guard_commands.CHANNEL_USAGE[guard_commands.BOT_ALLOW]


@pytest.mark.parametrize("verb", guard_commands.VERBS)
def test_run_unknown_action_returns_usage(store, verb):
    assert run(verb, "explode") == guard_commands.USAGE[verb]


def test_readonly_on_opens_guard_without_threads(store):
    assert run(guard_commands.READONLY, "on") == f"Read-only enabled in <#{CHANNEL}>"
    assert store.calls[0] == ("open", channelguards.READONLY, {"threads": False}, MOD)


def test_readonly_on_threads_opens_guard_with_threads(store):
    assert run(guard_commands.READONLY, "on threads") == f"Read-only enabled in <#{CHANNEL}>, threads included"
    assert store.calls[0][2] == {"threads": True}


def test_readonly_on_restores_allows_after_opening(store):
    run(guard_commands.READONLY, "on")

    assert ("restore", channelguards.READONLY) in store.calls


def test_readonly_on_when_already_on_reports_it(store):
    run(guard_commands.READONLY, "on")
    store.calls.clear()

    assert run(guard_commands.READONLY, "on") == f"Read-only already on in <#{CHANNEL}>"
    assert store.calls == []


def test_readonly_on_threads_when_on_without_threads_tunes(store):
    run(guard_commands.READONLY, "on")

    assert run(guard_commands.READONLY, "on threads") == f"Read-only enabled in <#{CHANNEL}>, threads included"
    assert ("tune", {"threads": True}, MOD) in store.calls


def test_readonly_on_with_unknown_option_returns_usage(store):
    assert run(guard_commands.READONLY, "on forever") == guard_commands.USAGE[guard_commands.READONLY]
    assert store.calls == []


def test_bot_allow_on_with_option_returns_usage(store):
    assert run(guard_commands.BOT_ALLOW, "on threads") == guard_commands.USAGE[guard_commands.BOT_ALLOW]


def test_on_outside_channel_appends_notice(store):
    store.inside = False
    store.joined = False

    assert run(guard_commands.READONLY, "on") == f"Read-only enabled in <#{CHANNEL}>. Nemo is not in this channel"


def test_on_outside_channel_joins_and_omits_notice(store):
    store.inside = False
    store.joined = True

    assert run(guard_commands.READONLY, "on") == f"Read-only enabled in <#{CHANNEL}>"


def test_off_lifts_guard(store):
    run(guard_commands.READONLY, "on")

    assert run(guard_commands.READONLY, "off") == f"Read-only disabled in <#{CHANNEL}>"
    assert store.guards == {}


@pytest.mark.parametrize(("verb", "text"), [
    (guard_commands.READONLY, "No read-only"),
    (guard_commands.ACCOUNT_AGE, "No new-account age"),
    (guard_commands.BOT_ALLOW, "No bot allow list"),
])
def test_off_without_guard_says_none(store, verb, text):
    assert run(verb, "off") == f"{text} in <#{CHANNEL}>"


def test_status_without_guard_says_off(store):
    assert run(guard_commands.READONLY) == f"Read-only off in <#{CHANNEL}>"


def test_status_lists_settings_and_allowed(store):
    run(guard_commands.READONLY, "on threads")
    run(guard_commands.READONLY, "allow", MEMBER)

    assert run(guard_commands.READONLY) == f"Read-only on in <#{CHANNEL}>, threads included, allowed: <@{MEMBER}>"


def test_status_without_allowed_omits_list(store):
    run(guard_commands.READONLY, "on")

    assert run(guard_commands.READONLY) == f"Read-only on in <#{CHANNEL}>"


def test_status_names_non_member_subject_by_label(store):
    run(guard_commands.BOT_ALLOW, "on")
    store.guards[(CHANNEL, channelguards.BOT_ALLOWLIST)]["allowed"].append(("B1APP", "Some App"))

    assert run(guard_commands.BOT_ALLOW).endswith("allowed: *Some App*")


def test_status_over_limit_counts_remainder(store):
    run(guard_commands.READONLY, "on")
    store.guards[(CHANNEL, channelguards.READONLY)]["allowed"] = [(f"U{one:04d}", None) for one in range(23)]

    assert run(guard_commands.READONLY).endswith("3 more")


def test_allow_adds_member(store):
    run(guard_commands.READONLY, "on")

    assert run(guard_commands.READONLY, "allow", MEMBER) == f"<@{MEMBER}> allowed in <#{CHANNEL}>"
    assert ("allow", MEMBER, MOD) in store.calls


def test_allow_twice_reports_already_allowed(store):
    run(guard_commands.READONLY, "on")
    run(guard_commands.READONLY, "allow", MEMBER)

    assert run(guard_commands.READONLY, "allow", MEMBER) == f"<@{MEMBER}> already allowed in <#{CHANNEL}>"
    assert [one for one in store.calls if one[0] == "allow"] == [("allow", MEMBER, MOD)]


def test_allow_without_guard_says_none(store):
    assert run(guard_commands.READONLY, "allow", MEMBER) == f"No read-only in <#{CHANNEL}>"


def test_allow_without_member_returns_subject_usage(store):
    run(guard_commands.READONLY, "on")

    assert run(guard_commands.READONLY, "allow") == guard_commands.SUBJECT_USAGE[guard_commands.READONLY]


def test_disallow_removes_member(store):
    run(guard_commands.READONLY, "on")
    run(guard_commands.READONLY, "allow", MEMBER)

    assert run(guard_commands.READONLY, "disallow", MEMBER) == f"<@{MEMBER}> removed from the allow list in <#{CHANNEL}>"


def test_disallow_member_not_listed_says_so(store):
    run(guard_commands.READONLY, "on")

    assert run(guard_commands.READONLY, "disallow", MEMBER) == f"<@{MEMBER}> is not on the allow list in <#{CHANNEL}>"


def test_disallow_without_member_returns_subject_usage(store):
    run(guard_commands.READONLY, "on")

    assert run(guard_commands.READONLY, "disallow") == guard_commands.SUBJECT_USAGE[guard_commands.READONLY]


def test_account_age_sets_days(store):
    assert run(guard_commands.ACCOUNT_AGE, "7d") == f"New-account age set to 7 days in <#{CHANNEL}>"
    assert store.calls[0] == ("open", channelguards.ACCOUNT_AGE, {"min_age_days": 7}, MOD)


def test_account_age_one_day_is_singular(store):
    assert run(guard_commands.ACCOUNT_AGE, "1") == f"New-account age set to 1 day in <#{CHANNEL}>"


def test_account_age_same_days_reports_already(store):
    run(guard_commands.ACCOUNT_AGE, "7d")

    assert run(guard_commands.ACCOUNT_AGE, "7") == f"New-account age already 7 days in <#{CHANNEL}>"


def test_account_age_new_days_tunes(store):
    run(guard_commands.ACCOUNT_AGE, "7d")

    assert run(guard_commands.ACCOUNT_AGE, "14d") == f"New-account age set to 14 days in <#{CHANNEL}>"
    assert ("tune", {"min_age_days": 14}, MOD) in store.calls


@pytest.mark.parametrize("text", ["0", "0d", "366d", "9999"])
def test_account_age_out_of_range_returns_days_usage(store, text):
    assert run(guard_commands.ACCOUNT_AGE, text) == guard_commands.DAYS_USAGE


def test_account_age_on_returns_usage(store):
    assert run(guard_commands.ACCOUNT_AGE, "on") == guard_commands.USAGE[guard_commands.ACCOUNT_AGE]


def test_account_age_status_names_days(store):
    run(guard_commands.ACCOUNT_AGE, "7d")

    assert run(guard_commands.ACCOUNT_AGE) == f"New-account age 7 days in <#{CHANNEL}>"


def test_account_age_allow_exempts_member(store):
    run(guard_commands.ACCOUNT_AGE, "7d")

    assert run(guard_commands.ACCOUNT_AGE, "allow", MEMBER) == f"<@{MEMBER}> allowed in <#{CHANNEL}>"


def test_bot_allow_on_opens_guard_without_settings(store):
    assert run(guard_commands.BOT_ALLOW, "on") == f"Bot allow list enabled in <#{CHANNEL}>"
    assert store.calls[0] == ("open", channelguards.BOT_ALLOWLIST, {}, MOD)


def test_bot_allow_add_and_remove_use_list_wording(store):
    run(guard_commands.BOT_ALLOW, "on")

    assert run(guard_commands.BOT_ALLOW, "add", BOT) == f"<@{BOT}> added to the allow list in <#{CHANNEL}>"
    assert run(guard_commands.BOT_ALLOW, "add", BOT) == f"<@{BOT}> already on the allow list in <#{CHANNEL}>"
    assert run(guard_commands.BOT_ALLOW, "remove", BOT) == f"<@{BOT}> removed from the allow list in <#{CHANNEL}>"


def test_bot_allow_allow_word_is_not_accepted(store):
    run(guard_commands.BOT_ALLOW, "on")

    assert run(guard_commands.BOT_ALLOW, "allow", BOT) == guard_commands.USAGE[guard_commands.BOT_ALLOW]


def test_verbs_need_channel_guard_capability():
    assert all(command.NEEDED[verb] == "channel.guard" for verb in guard_commands.VERBS)


def test_verbs_are_command_verbs():
    assert set(guard_commands.VERBS) <= set(command.VERBS)


def test_parse_command_allow_returns_member_and_channel_body():
    verb, target, body = command.parse_command("readonly <#C1LOUNGE|lounge> allow <@U1MEMBER|someone>")

    assert (verb, target, body) == (guard_commands.READONLY, MEMBER, "<#C1LOUNGE|lounge> allow")


def test_parse_command_accountage_returns_no_target():
    verb, target, body = command.parse_command("accountage <#C1LOUNGE|lounge> 7d")

    assert (verb, target, body) == (guard_commands.ACCOUNT_AGE, None, "<#C1LOUNGE|lounge> 7d")


def test_channel_and_text_prefers_channel_mention():
    assert command.channel_and_text("<#C9OTHER|other> on", HERE) == ("C9OTHER", "on")


def test_channel_and_text_defaults_to_current_channel():
    assert command.channel_and_text("allow  ", HERE) == (HERE, "allow")


def test_help_lists_channel_guard_commands_for_channel_guard():
    help_text = command.helping.fallback_text({"channel.guard"})

    assert "/nemo readonly" in help_text and "/nemo accountage" in help_text and "/nemo botallow" in help_text
    assert "/nemo readonly" not in command.helping.fallback_text({"case.read"})
