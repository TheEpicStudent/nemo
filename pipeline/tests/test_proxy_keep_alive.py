import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from lib import proxy_client
from lib.proxy_client import ProxyClient, ProxyError


class Proxy:
    def __init__(self, status=200, close_after_first=False):
        self.status = status
        self.close_after_first = close_after_first
        self.connections = set()
        self.calls = 0
        proxy_server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            disable_nagle_algorithm = True

            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                proxy_server.connections.add(self.client_address[1])
                proxy_server.calls += 1
                body = json.dumps({"ok": proxy_server.status < 400, "detail": "budget: spent"}).encode()
                self.send_response(proxy_server.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                if proxy_server.status == 429:
                    self.send_header("Retry-After", "1")
                self.end_headers()
                self.wfile.write(body)
                if proxy_server.close_after_first and proxy_server.calls == 1:
                    self.close_connection = True

            def log_message(self, *args):
                return None

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def client(self, keep_alive=True):
        return ProxyClient(url=self.url, token="t", keep_alive=keep_alive)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def proxy():
    proxies = []

    def start(**kwargs):
        one = Proxy(**kwargs)
        proxies.append(one)
        return one

    yield start
    proxy_client._connections.pool = {}
    for one in proxies:
        one.stop()


def test_call_repeated_on_one_thread_reuses_one_connection(proxy):
    server = proxy()
    client = server.client()

    for _ in range(3):
        assert client.call("chat.delete", {"ts": "1.1"}, max_retries=0) == {
            "ok": True, "detail": "budget: spent"}

    assert server.calls == 3
    assert len(server.connections) == 1


def test_call_from_new_client_on_same_thread_reuses_connection(proxy):
    server = proxy()

    server.client().call("chat.delete", max_retries=0)
    server.client().call("chat.delete", max_retries=0)

    assert len(server.connections) == 1


def test_call_without_keep_alive_opens_connection_per_call(proxy):
    server = proxy()
    client = server.client(keep_alive=False)

    client.call("chat.delete", max_retries=0)
    client.call("chat.delete", max_retries=0)

    assert len(server.connections) == 2


def test_call_after_keepalive_idle_seconds_opens_new_connection(proxy, monkeypatch):
    server = proxy()
    client = server.client()
    monkeypatch.setattr(proxy_client, "KEEPALIVE_IDLE_SECONDS", -1)

    client.call("chat.delete", max_retries=0)
    client.call("chat.delete", max_retries=0)

    assert len(server.connections) == 2


def test_call_after_server_closes_connection_retries_on_new_connection(proxy):
    server = proxy(close_after_first=True)
    client = server.client()

    client.call("chat.delete", max_retries=0)
    assert client.call("chat.delete", max_retries=0)["ok"] is True

    assert server.calls == 2
    assert len(server.connections) == 2


def test_call_from_other_thread_opens_separate_connection(proxy):
    server = proxy()
    client = server.client()

    client.call("chat.delete", max_retries=0)
    other = threading.Thread(target=lambda: client.call("chat.delete", max_retries=0))
    other.start()
    other.join()

    assert len(server.connections) == 2


def test_call_with_429_raises_proxy_error_with_http_status(proxy):
    server = proxy(status=429)

    with pytest.raises(ProxyError) as caught:
        server.client().call("chat.delete", max_retries=0)

    assert caught.value.http_status == 429
    assert "budget: spent" in str(caught.value)


def test_privileged_proxy_enables_keep_alive(monkeypatch):
    from bot.core import privileged

    monkeypatch.setenv("PROXY_TOKEN_NEMO", "t")
    monkeypatch.setenv("INTERNAL_PROXY_URL", "http://127.0.0.1:1")

    assert privileged.proxy().keep_alive is True


def test_call_connection_sets_tcp_nodelay(proxy):
    import socket

    server = proxy()
    server.client().call("chat.delete", max_retries=0)

    (conn, _at), = proxy_client._connections.pool.values()
    assert conn.sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
