import pytest

from lib import config, slack_connection

SECRET = "s" * 32


@pytest.mark.parametrize(("value", "enabled"), [
    (None, True), ("", True), ("true", True), ("1", True), ("false", False), ("FALSE", False), ("0", False),
    ("off", False), (" no ", False),
])
def test_socket_mode_enabled_defaults_to_on_and_reads_falsey_values(value, enabled):
    env = {} if value is None else {slack_connection.SOCKET_MODE: value}

    assert slack_connection.socket_mode_enabled(env) is enabled


def test_credential_variables_follow_the_mode():
    assert slack_connection.credential_variables(["relay", "nemo"], {}) == ["RELAY_APP_TOKEN", "NEMO_APP_TOKEN"]
    assert slack_connection.credential_variables(["nemo"], {"SLACK_SOCKET_MODE": "false"}) == ["NEMO_SIGNING_SECRET"]


def test_signing_secret_is_only_returned_outside_socket_mode_and_is_stripped():
    http = {"SLACK_SOCKET_MODE": "false", "NEMO_SIGNING_SECRET": f" {SECRET} "}

    assert slack_connection.signing_secret("nemo", http) == SECRET
    assert slack_connection.signing_secret("nemo", {"NEMO_SIGNING_SECRET": SECRET}) is None


def test_weak_signing_secrets_names_short_values_only_outside_socket_mode():
    env = {"SLACK_SOCKET_MODE": "false", "NEMO_SIGNING_SECRET": "short", "RELAY_SIGNING_SECRET": SECRET}

    assert slack_connection.weak_signing_secrets(["nemo", "relay"], env) == ["NEMO_SIGNING_SECRET"]
    assert slack_connection.weak_signing_secrets(["nemo"], {"NEMO_SIGNING_SECRET": "short"}) == []


def test_http_address_defaults_to_loopback():
    assert slack_connection.http_address({}) == ("127.0.0.1", 3100)
    assert slack_connection.http_address({"SLACK_HTTP_HOST": "0.0.0.0", "SLACK_HTTP_PORT": "8080"}) == ("0.0.0.0", 8080)


def test_bot_roles_require_the_credentials_of_the_mode():
    base = {name: "x" for name in config.ROLES["bot.nemo"]["required"]}

    assert config.missing("bot.nemo", base) == ["NEMO_APP_TOKEN"]
    assert config.missing("bot.nemo", {**base, "SLACK_SOCKET_MODE": "false"}) == ["NEMO_SIGNING_SECRET"]
    assert config.missing("bot.nemo", {**base, "NEMO_APP_TOKEN": "x"}) == []


def test_bot_role_reports_short_signing_secrets():
    env = {"SLACK_SOCKET_MODE": "false", "NEMO_SIGNING_SECRET": "short"}

    assert config.weak("bot.nemo", env) == ["NEMO_SIGNING_SECRET"]
    assert config.weak("serve", env) == []


def test_web_role_refuses_signing_secrets():
    assert {"NEMO_SIGNING_SECRET", "RELAY_SIGNING_SECRET"} <= set(config.FORBIDDEN["serve"])
    assert config.forbidden("serve", {"NEMO_SIGNING_SECRET": SECRET}) == ["NEMO_SIGNING_SECRET"]


def test_bot_roles_refuse_user_tokens():
    assert {"SLACK_TOKEN", "SLACK_ADMIN_TOKEN"} <= set(config.FORBIDDEN["bot.nemo"])
