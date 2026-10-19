import os

from slack_bolt import App

from bot.relay import dm, shortcut


def build(on_submit=None):
    app = App(token=os.environ["RELAY_BOT_TOKEN"], raise_error_for_unhandled_request=False)
    dm.register(app, on_submit)
    shortcut.register(app, on_submit)
    return app


def app_token():
    return os.environ["RELAY_APP_TOKEN"]
