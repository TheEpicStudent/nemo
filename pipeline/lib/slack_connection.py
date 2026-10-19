import os

SOCKET_MODE = "SLACK_SOCKET_MODE"
HTTP_HOST = "SLACK_HTTP_HOST"
HTTP_PORT = "SLACK_HTTP_PORT"

DEFAULT_HTTP_HOST = "127.0.0.1"
DEFAULT_HTTP_PORT = 3100
MIN_SIGNING_SECRET_LENGTH = 32

DISABLED_VALUES = ("false", "0", "no", "off")


def socket_mode_enabled(env=None):
    env = env if env is not None else os.environ
    return (env.get(SOCKET_MODE) or "true").strip().lower() not in DISABLED_VALUES


def app_token_variable(app):
    return f"{app.upper()}_APP_TOKEN"


def signing_secret_variable(app):
    return f"{app.upper()}_SIGNING_SECRET"


def credential_variables(apps, env=None):
    name = app_token_variable if socket_mode_enabled(env) else signing_secret_variable
    return [name(app) for app in apps]


def app_token(app, env=None):
    env = env if env is not None else os.environ
    return env[app_token_variable(app)]


def signing_secret(app, env=None):
    if socket_mode_enabled(env):
        return None
    env = env if env is not None else os.environ
    return env[signing_secret_variable(app)].strip()


def weak_signing_secrets(apps, env=None):
    if socket_mode_enabled(env):
        return []
    env = env if env is not None else os.environ
    names = [signing_secret_variable(app) for app in apps]
    return [name for name in names if env.get(name) and len(env[name].strip()) < MIN_SIGNING_SECRET_LENGTH]


def http_address(env=None):
    env = env if env is not None else os.environ
    host = (env.get(HTTP_HOST) or DEFAULT_HTTP_HOST).strip()
    port = int((env.get(HTTP_PORT) or DEFAULT_HTTP_PORT))
    return host, port
