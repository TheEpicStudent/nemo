import os

from slack_bolt import App

from bot.relay import dm, shortcut
from lib import slack_connection

NAME = "relay"


def build(on_submit=None):
    app = App(
        token=os.environ["RELAY_BOT_TOKEN"],
        signing_secret=slack_connection.signing_secret(NAME),
        request_verification_enabled=True,
        raise_error_for_unhandled_request=False,
    )
    dm.register(app, on_submit)
    shortcut.register(app, on_submit)
    return app
