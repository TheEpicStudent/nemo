from slack_sdk import WebClient

from lib import proxy_client, slack_dry_run


def test_enabled_reads_the_setting():
    assert slack_dry_run.enabled({"NEMO_DRY_RUN": "true"})
    assert not slack_dry_run.enabled({"NEMO_DRY_RUN": "0"})
    assert not slack_dry_run.enabled({})


def test_is_read_for_reads_and_writes():
    assert slack_dry_run.is_read("conversations.replies")
    assert slack_dry_run.is_read("users.info")
    assert not slack_dry_run.is_read("chat.postMessage")
    assert not slack_dry_run.is_read("reactions.add")
    assert not slack_dry_run.is_read("scim.users.deactivate")


def test_install_holds_writes_and_uninstall_restores():
    original = WebClient.api_call
    before = slack_dry_run.held_count()
    assert slack_dry_run.install()
    try:
        response = WebClient(token="xoxb-test").chat_postMessage(channel="C0FIRE", text="hello")
        assert response["ok"] and response["channel"] == "C0FIRE" and response["ts"]
        held = proxy_client.ProxyClient(url="https://proxy.test", token="t").call(
            "chat.delete", {"channel": "C0FIRE", "ts": "1.2"}, credential="admin")
        assert held["ok"]
        assert slack_dry_run.held_count() == before + 2
        assert slack_dry_run.held[-1][0] == "chat.delete"
    finally:
        assert slack_dry_run.uninstall()
    assert WebClient.api_call is original
