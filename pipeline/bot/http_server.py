import asyncio
import collections
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import uvicorn
from slack_bolt.adapter.asgi.http_response import AsgiHttpResponse
from slack_bolt.request import BoltRequest
from slack_bolt.response import BoltResponse

log = logging.getLogger("bot.http")

HEALTH_PATH = "/healthz"
EVENTS_PATH = "/slack/{app}/events"
MAX_BODY_BYTES = 4 * 1024 * 1024
HANDLER_THREADS = 32
START_TIMEOUT_SECONDS = 10
STOP_TIMEOUT_SECONDS = 10
DEDUPLICATION_SECONDS = 600
DEDUPLICATION_LIMIT = 50_000
KEEP_ALIVE_SECONDS = 5
MAX_HEADER_BYTES = 65_536
QUIET_LOGGERS = ("slack_bolt", "slack_sdk", "uvicorn", "uvicorn.error", "uvicorn.access")

TEXT = {"content-type": ["text/plain; charset=utf-8"]}


def events_path(app):
    return EVENTS_PATH.format(app=app)


def quiet_loggers():
    for name in QUIET_LOGGERS:
        logger = logging.getLogger(name)
        if logger.getEffectiveLevel() < logging.INFO:
            logger.setLevel(logging.INFO)


class EventDeduplicator:
    def __init__(self, ttl=DEDUPLICATION_SECONDS, limit=DEDUPLICATION_LIMIT, clock=time.monotonic):
        self.ttl = ttl
        self.limit = limit
        self.clock = clock
        self.seen_at = collections.OrderedDict()
        self.lock = threading.Lock()

    def seen(self, event_id):
        now = self.clock()
        with self.lock:
            while self.seen_at and (len(self.seen_at) >= self.limit
                                    or now - next(iter(self.seen_at.values())) > self.ttl):
                self.seen_at.popitem(last=False)
            if event_id in self.seen_at:
                return True
            self.seen_at[event_id] = now
            return False


def skip_duplicate_events(deduplicator):
    def middleware(body, next):
        event_id = body.get("event_id") if isinstance(body, dict) else None
        if event_id and deduplicator.seen(event_id):
            return BoltResponse(status=200, body="")
        return next()

    return middleware


def add_event_deduplication(app, deduplicator=None):
    app.middleware(skip_duplicate_events(deduplicator or EventDeduplicator()))


class TooLarge(Exception):
    pass


async def read_body(receive, limit=MAX_BODY_BYTES):
    chunks = bytearray()
    while True:
        message = await receive()
        if message["type"] != "http.request":
            raise ConnectionError("client went away")
        chunks.extend(message.get("body", b""))
        if len(chunks) > limit:
            raise TooLarge
        if not message.get("more_body", False):
            return bytes(chunks)


async def reply(send, status, body="", headers=None):
    response = AsgiHttpResponse(status=status, headers=headers or TEXT, body=body)
    await send(response.get_response_start())
    await send(response.get_response_body())


def header_map(scope):
    return {name.decode("latin-1").lower(): value.decode("latin-1") for name, value in scope["headers"]}


class SlackEndpoint:
    def __init__(self, app, executor):
        self.app = app
        self.executor = executor

    async def __call__(self, scope, receive, send):
        if scope["method"] != "POST":
            return await reply(send, 405, "Method Not Allowed", {**TEXT, "allow": ["POST"]})

        headers = header_map(scope)
        declared = headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > MAX_BODY_BYTES):
            return await reply(send, 413, "Payload Too Large")

        try:
            raw = await read_body(receive)
            body = raw.decode("utf-8")
        except TooLarge:
            return await reply(send, 413, "Payload Too Large")
        except (UnicodeDecodeError, ConnectionError):
            return await reply(send, 400, "Bad Request")

        request = BoltRequest(body=body, query=scope["query_string"].decode("latin-1"), headers=headers)
        bolt_response = await asyncio.get_running_loop().run_in_executor(self.executor, self.app.dispatch, request)
        await reply(send, bolt_response.status, bolt_response.body, bolt_response.headers)


class Router:
    def __init__(self, endpoints):
        self.endpoints = endpoints

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            raise TypeError(f"Unsupported scope type: {scope['type']!r}")

        path = scope["path"]
        if path == HEALTH_PATH:
            if scope["method"] not in ("GET", "HEAD"):
                return await reply(send, 405, "Method Not Allowed", {**TEXT, "allow": ["GET, HEAD"]})
            return await reply(send, 200, "ok")

        endpoint = self.endpoints.get(path)
        if endpoint is None:
            return await reply(send, 404, "Not Found")
        return await endpoint(scope, receive, send)


def build_router(apps, executor):
    endpoints = {events_path(name): SlackEndpoint(app, executor) for name, app in apps.items()}
    return Router(endpoints)


class HttpServer:
    def __init__(self, apps, host, port):
        quiet_loggers()
        for app in apps.values():
            add_event_deduplication(app)
        self.host = host
        self.port = port
        self.paths = [events_path(name) for name in apps]
        self.executor = ThreadPoolExecutor(max_workers=HANDLER_THREADS, thread_name_prefix="slack-http")
        self.server = uvicorn.Server(uvicorn.Config(
            build_router(apps, self.executor),
            host=host,
            port=port,
            lifespan="off",
            access_log=False,
            server_header=False,
            log_level="warning",
            timeout_keep_alive=KEEP_ALIVE_SECONDS,
            h11_max_incomplete_event_size=MAX_HEADER_BYTES,
            proxy_headers=False,
        ))
        self.thread = threading.Thread(target=self.serve, name="slack-http-server", daemon=True)

    def serve(self):
        try:
            self.server.run()
        except SystemExit:
            log.error("http: the server stopped on %s:%s", self.host, self.port)

    def start(self):
        self.thread.start()
        deadline = time.monotonic() + START_TIMEOUT_SECONDS
        while not self.server.started:
            if not self.thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError(f"the Slack HTTP server did not start on {self.host}:{self.port}")
            time.sleep(0.05)
        log.info("http: listening on %s:%s for %s", self.host, self.port, ", ".join(self.paths))

    def stop(self):
        self.server.should_exit = True
        self.thread.join(STOP_TIMEOUT_SECONDS)
        self.executor.shutdown(wait=False, cancel_futures=True)
