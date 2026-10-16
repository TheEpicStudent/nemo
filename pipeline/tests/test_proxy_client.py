from lib.proxy_client import ProxyClient, plaintext_refused


def test_plaintext_refused_https_returns_none():
    assert plaintext_refused("https://proxy.example.com", allow_plaintext="") is None


def test_plaintext_refused_loopback_returns_none():
    assert plaintext_refused("http://127.0.0.1:8002", allow_plaintext="") is None
    assert plaintext_refused("http://localhost:8002", allow_plaintext="") is None
    assert plaintext_refused("http://host.docker.internal:8002", allow_plaintext="") is None


def test_plaintext_refused_remote_host_returns_reason():
    assert plaintext_refused("http://proxy.example.com:8002", allow_plaintext="") is not None


def test_plaintext_refused_allow_plaintext_flag_controls_remote_host():
    assert plaintext_refused("http://proxy.example.com", allow_plaintext="true") is None
    assert plaintext_refused("http://proxy.example.com", allow_plaintext="no") is not None


class PagingClient(ProxyClient):
    def __init__(self, pages):
        self.pages = pages
        self.cursor_marks = []

    def call(self, method, params, **kwargs):
        self.cursor_marks.append(params.get("cursor_mark"))
        return self.pages[len(self.cursor_marks) - 1]


def page(items, cursor):
    return {"rows": items, "next_cursor_mark": cursor}


def test_paginate_empty_page_stops_by_default():
    client = PagingClient([page([{"n": 1}], "c1"), page([], "c2"), page([{"n": 2}], None)])

    rows = list(client.paginate("m", {}, "rows", cursor_param="cursor_mark"))

    assert rows == [{"n": 1}]
    assert len(client.cursor_marks) == 2


def test_paginate_allow_empty_pages_reads_past_empty_page():
    client = PagingClient([page([{"n": 1}], "c1"), page([], "c2"), page([{"n": 2}], None)])

    rows = list(client.paginate(
        "m", {}, "rows", cursor_param="cursor_mark", allow_empty_pages=True))

    assert rows == [{"n": 1}, {"n": 2}]
    assert len(client.cursor_marks) == 3


def test_paginate_allow_empty_pages_stops_when_cursor_ends():
    client = PagingClient([page([], "c1"), page([], "c2"), page([], None)])

    rows = list(client.paginate(
        "m", {}, "rows", cursor_param="cursor_mark", allow_empty_pages=True))

    assert rows == []
    assert len(client.cursor_marks) == 3


def test_raise_for_status_proxy_fault_raises_proxy_error_with_status():
    import io
    import urllib.error
    from email.message import Message
    from lib.proxy_client import ProxyClient, ProxyError
    headers = Message()
    headers["X-Fault-Origin"] = "proxy"
    exc = urllib.error.HTTPError("http://x/call", 503, "Service Unavailable", headers, io.BytesIO(b'{"detail":"budget: spent"}'))
    try:
        ProxyClient(url="http://localhost:1", token="t")._raise_for_status(exc)
    except ProxyError as error:
        assert error.http_status == 503
        assert error.had_fault_body is True
        assert "budget: spent" in str(error)
    else:
        raise AssertionError("expected ProxyError")


def test_raise_for_status_without_fault_header_sets_had_fault_body_false():
    import io
    import urllib.error
    from email.message import Message
    from lib.proxy_client import ProxyClient, ProxyError
    exc = urllib.error.HTTPError("http://x/call", 504, "Gateway Timeout", Message(), io.BytesIO(b"<html>"))
    try:
        ProxyClient(url="http://localhost:1", token="t")._raise_for_status(exc)
    except ProxyError as error:
        assert error.http_status == 504
        assert error.had_fault_body is False


def test_retry_after_uses_header_else_default():
    from email.message import Message
    from lib.proxy_client import retry_after

    class Exc:
        headers = Message()
    Exc.headers["Retry-After"] = "7"
    assert retry_after(Exc(), 2) == 7.0

    class Bad:
        headers = Message()
    Bad.headers["Retry-After"] = "soon"
    assert retry_after(Bad(), 3) == 3.0
    assert retry_after(type("E", (), {"headers": Message()})(), 4) == 4.0


def test_raise_for_status_upstream_unreachable_raises_proxy_unavailable_error():
    import io
    import urllib.error
    from email.message import Message
    from lib.proxy_client import ProxyClient, ProxyUnavailableError
    headers = Message()
    headers["X-Fault-Origin"] = "proxy"
    body = io.BytesIO(b'{"detail":"upstream unreachable: URLError: <urlopen error [Errno -3] Temporary failure in name resolution>"}')
    exc = urllib.error.HTTPError("http://localhost:1/call", 502, "Bad Gateway", headers, body)
    try:
        ProxyClient(url="http://localhost:1", token="t")._raise_for_status(exc)
    except ProxyUnavailableError as error:
        assert error.http_status == 502 and error.had_fault_body is True
        assert "name resolution" in str(error)
    else:
        raise AssertionError("expected ProxyUnavailableError")
