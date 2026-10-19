import contextlib

import pytest

from bot.nemo import channels, surface

USER = "UMOD"
CHANNEL = "C0PUBLIC"
RESPONSE_URL = "https://hooks.slack.com/actions/T1/1/abc"


class Slack:
    def __init__(self, fail=None):
        self.fail = fail
        self.ephemerals = []
        self.calls = []

    def chat_postEphemeral(self, **kwargs):
        self.calls.append("ephemeral")
        if self.fail:
            raise RuntimeError(self.fail)
        self.ephemerals.append(kwargs)

    def chat_postMessage(self, **kwargs):
        raise AssertionError("no DM fallback")


class Webhook:
    sent = []
    status_code = 200
    fail = False
    reject_thread = False

    def __init__(self, url):
        self.url = url

    def send(self, **kwargs):
        if Webhook.fail or (Webhook.reject_thread and "thread_ts" in kwargs):
            raise RuntimeError("invalid_payload")
        Webhook.sent.append((self.url, kwargs))
        return self


@pytest.fixture
def world(monkeypatch):
    state = {"inside": False, "joinable": True, "joined": []}

    @contextlib.contextmanager
    def fake_session():
        yield object()

    Webhook.sent, Webhook.status_code, Webhook.fail, Webhook.reject_thread = [], 200, False, False
    monkeypatch.setattr(surface, "session", fake_session)
    monkeypatch.setattr(surface, "WebhookClient", Webhook)
    monkeypatch.setattr(channels, "is_inside", lambda conn, channel_id: state["inside"])
    monkeypatch.setattr(channels, "joinable", lambda conn, channel_id: state["joinable"])
    monkeypatch.setattr(channels, "join", lambda client, conn, channel_id, by=None, verb="joined":
                        state["joined"].append((channel_id, by)) or True)
    return state


def ctx_for(client, **body):
    entry = surface.SurfaceEntry(surface.SHORTCUT, "lock_thread", None, lambda ctx: None)
    base = {"user": {"id": USER}, "channel": {"id": CHANNEL}, "message": {"ts": "1.1", "thread_ts": "1.0"}}
    base.update(body)
    return surface.Ctx(entry, base, client, lambda: None)


def test_post_ephemeral_joins_a_public_channel_before_posting(world):
    client = Slack()

    assert ctx_for(client).post_ephemeral("Thread locked") is True
    assert world["joined"] == [(CHANNEL, USER)]
    assert client.ephemerals[0]["thread_ts"] == "1.0" and client.ephemerals[0]["user"] == USER


@pytest.mark.parametrize(("inside", "joinable", "channel"), [
    (True, True, CHANNEL),
    (False, False, CHANNEL),
    (False, True, "D0DIRECT"),
    (False, True, "G0LEGACY"),
])
def test_post_ephemeral_skips_the_join_when_inside_private_or_not_a_channel(world, inside, joinable, channel):
    world.update(inside=inside, joinable=joinable)

    ctx_for(Slack(), channel={"id": channel}).post_ephemeral("Thread locked")

    assert world["joined"] == []


def test_post_ephemeral_failure_falls_back_to_the_response_url_without_dm(world):
    client = Slack(fail="not_in_channel")

    assert ctx_for(client, response_url=RESPONSE_URL).post_ephemeral("Thread locked") is True
    assert Webhook.sent == [(RESPONSE_URL, {"text": "Thread locked", "response_type": "ephemeral",
                                            "thread_ts": "1.0"})]


def test_post_ephemeral_retries_the_response_url_without_thread_when_slack_rejects_it(world):
    Webhook.reject_thread = True

    assert ctx_for(Slack(fail="not_in_channel"), response_url=RESPONSE_URL).post_ephemeral("Thread locked") is True
    assert Webhook.sent == [(RESPONSE_URL, {"text": "Thread locked", "response_type": "ephemeral"})]


def test_post_ephemeral_failure_without_response_url_only_logs(world, caplog):
    caplog.set_level("WARNING", logger="bot.nemo")

    assert ctx_for(Slack(fail="channel_not_found")).post_ephemeral("Thread locked") is False
    assert "shortcut lock_thread could not say 'Thread locked' in C0PUBLIC" in caplog.text
    assert Webhook.sent == []


def test_post_ephemeral_for_another_channel_does_not_use_the_response_url(world):
    client = Slack(fail="not_in_channel")

    assert ctx_for(client, response_url=RESPONSE_URL).post_ephemeral("Thread locked", "C0OTHER") is False
    assert Webhook.sent == []


def test_post_ephemeral_when_the_response_url_refuses_returns_false(world):
    Webhook.fail = True

    assert ctx_for(Slack(fail="not_in_channel"), response_url=RESPONSE_URL).post_ephemeral("Thread locked") is False


def test_post_ephemeral_with_failed_join_still_posts(world, monkeypatch):
    monkeypatch.setattr(channels, "join", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("ratelimited")))
    client = Slack()

    assert ctx_for(client).post_ephemeral("Thread locked") is True
