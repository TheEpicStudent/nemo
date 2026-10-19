import asyncio
import json
import logging
import socket
import threading
import time
import urllib.request

import pytest
from slack_bolt import App
from slack_sdk.signature import SignatureVerifier
from slack_bolt.authorization import AuthorizeResult

from bot import http_server

SECRET = "a" * 32
OTHER_SECRET = "b" * 32
NEMO_PATH = http_server.events_path("nemo")
RELAY_PATH = http_server.events_path("relay")


def authorize(**kwargs):
    return AuthorizeResult(enterprise_id=None, team_id="T1", bot_token="xoxb-test", bot_user_id="UBOT")


def build_app(secret=SECRET):
    received = []
    app = App(signing_secret=secret, authorize=authorize, request_verification_enabled=True,
              raise_error_for_unhandled_request=False)
    handled = threading.Event()

    @app.event("message")
    def on_message(event):
        received.append(event["ts"])
        handled.set()

    return app, received, handled


def event_body(event_id="Ev1", ts="1.1"):
    return json.dumps({
        "token": "legacy", "team_id": "T1", "api_app_id": "A1", "type": "event_callback", "event_id": event_id,
        "event_time": 1, "authorizations": [{"team_id": "T1", "user_id": "UBOT", "is_bot": True}],
        "event": {"type": "message", "channel": "C1", "user": "U1", "ts": ts, "text": "hello"},
    })


def signed_headers(body, secret=SECRET, timestamp=None):
    timestamp = str(int(time.time()) if timestamp is None else timestamp)
    signature = SignatureVerifier(secret or "x").generate_signature(timestamp=timestamp, body=body)
    return {"x-slack-signature": signature, "x-slack-request-timestamp": timestamp,
            "content-type": "application/json"}


def call(router, path, method="POST", body="", headers=None, chunks=None):
    headers = headers or {}
    raw = [(name.encode(), value.encode()) for name, value in headers.items()]
    scope = {"type": "http", "method": method, "path": path, "query_string": b"", "headers": raw}
    parts = chunks if chunks is not None else [body.encode()]
    messages = [{"type": "http.request", "body": part, "more_body": at < len(parts) - 1}
                for at, part in enumerate(parts)]
    sent = []

    async def receive():
        return messages.pop(0) if messages else {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    asyncio.run(router(scope, receive, send))
    start = next(one for one in sent if one["type"] == "http.response.start")
    body_out = next(one for one in sent if one["type"] == "http.response.body")["body"].decode()
    return start["status"], body_out


@pytest.fixture
def server():
    nemo, nemo_received, nemo_handled = build_app()
    relay, relay_received, _ = build_app(OTHER_SECRET)
    for app in (nemo, relay):
        http_server.add_event_deduplication(app)
    executor = http_server.ThreadPoolExecutor(max_workers=4)
    router = http_server.build_router({"nemo": nemo, "relay": relay}, executor)
    yield router, nemo_received, nemo_handled, relay_received
    executor.shutdown(wait=True)


def test_valid_signature_is_accepted_and_handled(server):
    router, received, handled, _ = server
    body = event_body()

    status, _ = call(router, NEMO_PATH, body=body, headers=signed_headers(body))

    assert status == 200
    assert handled.wait(2) and received == ["1.1"]


@pytest.mark.parametrize("make_headers", [
    lambda body: {},
    lambda body: {**signed_headers(body), "x-slack-signature": "v0=" + "0" * 64},
    lambda body: signed_headers(body, secret=OTHER_SECRET),
    lambda body: signed_headers(body, timestamp=int(time.time()) - 3600),
    lambda body: signed_headers(body, secret=""),
])
def test_invalid_signature_is_rejected_without_running_a_listener(server, make_headers):
    router, received, handled, _ = server
    body = event_body()

    status, _ = call(router, NEMO_PATH, body=body, headers=make_headers(body))

    assert status == 401
    assert not handled.wait(0.2) and received == []


def test_request_signed_with_another_apps_secret_is_rejected(server):
    router, received, handled, relay_received = server
    body = event_body()

    status, _ = call(router, RELAY_PATH, body=body, headers=signed_headers(body))

    assert status == 401 and relay_received == []


def test_each_app_is_served_on_its_own_path(server):
    router, received, handled, relay_received = server
    body = event_body(event_id="Ev9", ts="9.9")

    status, _ = call(router, RELAY_PATH, body=body, headers=signed_headers(body, secret=OTHER_SECRET))
    time.sleep(0.3)

    assert status == 200 and relay_received == ["9.9"] and received == []


def test_duplicate_event_id_is_acknowledged_and_handled_once(server):
    router, received, handled, _ = server
    body = event_body(event_id="EvDup")

    first, _ = call(router, NEMO_PATH, body=body, headers=signed_headers(body))
    handled.wait(2)
    second, _ = call(router, NEMO_PATH, body=body, headers=signed_headers(body))
    time.sleep(0.3)

    assert (first, second) == (200, 200) and received == ["1.1"]


def test_unsigned_duplicate_does_not_mark_an_event_as_seen(server):
    router, received, handled, _ = server
    body = event_body(event_id="EvForged")

    call(router, NEMO_PATH, body=body, headers={})
    status, _ = call(router, NEMO_PATH, body=body, headers=signed_headers(body))

    assert status == 200 and handled.wait(2) and received == ["1.1"]


def test_declared_body_over_the_limit_is_refused(server):
    router, *_ = server

    status, _ = call(router, NEMO_PATH, body="{}", headers={"content-length": str(http_server.MAX_BODY_BYTES + 1)})

    assert status == 413


def test_streamed_body_over_the_limit_is_refused(server):
    router, *_ = server
    chunk = b"x" * (1024 * 1024)

    status, _ = call(router, NEMO_PATH, chunks=[chunk] * 5)

    assert status == 413


def test_invalid_content_length_and_encoding_are_refused(server):
    router, *_ = server

    assert call(router, NEMO_PATH, body="{}", headers={"content-length": "-1"})[0] == 413
    assert call(router, NEMO_PATH, chunks=[b"\xff\xfe"])[0] == 400


@pytest.mark.parametrize(("method", "path", "status"), [
    ("GET", NEMO_PATH, 405),
    ("PUT", NEMO_PATH, 405),
    ("POST", "/slack/events", 404),
    ("POST", "/", 404),
    ("GET", "/metrics", 404),
])
def test_other_methods_and_paths_are_refused(server, method, path, status):
    router, *_ = server

    assert call(router, path, method=method)[0] == status


def test_health_check_answers_without_slack_headers(server):
    router, *_ = server

    assert call(router, http_server.HEALTH_PATH, method="GET") == (200, "ok")
    assert call(router, http_server.HEALTH_PATH, method="POST")[0] == 405


def test_rejected_request_does_not_log_signature_or_body(server, caplog):
    router, *_ = server
    logging.getLogger("slack_bolt").setLevel(logging.DEBUG)
    http_server.quiet_loggers()
    caplog.set_level(logging.DEBUG)
    body = event_body(event_id="EvSecret")

    call(router, NEMO_PATH, body=body, headers={**signed_headers(body), "x-slack-signature": "v0=feedface"})

    assert "feedface" not in caplog.text and "EvSecret" not in caplog.text and "hello" not in caplog.text


def test_quiet_loggers_raise_debug_loggers_to_info():
    for name in http_server.QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG)

    http_server.quiet_loggers()

    assert all(logging.getLogger(name).getEffectiveLevel() >= logging.INFO for name in http_server.QUIET_LOGGERS)


def test_deduplicator_expires_old_ids_and_bounds_memory():
    now = [0.0]
    dedupe = http_server.EventDeduplicator(ttl=10, limit=3, clock=lambda: now[0])

    assert [dedupe.seen(one) for one in ("a", "b", "a")] == [False, False, True]
    now[0] = 11
    assert dedupe.seen("a") is False
    for one in ("c", "d", "e", "f"):
        dedupe.seen(one)
    assert len(dedupe.seen_at) <= 3


def free_port():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def test_http_server_serves_health_and_stops():
    app, *_ = build_app()
    port = free_port()
    running = http_server.HttpServer({"nemo": app}, "127.0.0.1", port)
    running.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=5) as response:
            assert response.status == 200 and response.read() == b"ok"
            assert response.headers.get("server") is None
    finally:
        running.stop()

    assert not running.thread.is_alive()


def test_http_server_start_fails_when_the_port_is_taken():
    app, *_ = build_app()
    with socket.socket() as holder:
        holder.bind(("127.0.0.1", 0))
        holder.listen()
        running = http_server.HttpServer({"nemo": app}, "127.0.0.1", holder.getsockname()[1])
        with pytest.raises(RuntimeError):
            running.start()
