import psycopg
import pytest
from slack_sdk.errors import SlackApiError

from lib import faults
from lib.db import SyncCancelled
from lib.proxy_client import InternalApiError, InternalAuthError, ProxyError, ProxyUnavailableError
from lib.walk import WalkMismatchError


def slack_error(error):
    return SlackApiError("boom", {"ok": False, "error": error})


@pytest.mark.parametrize("exc, expected", [
    (SyncCancelled("cancel requested"), "cancelled"),
    (InternalAuthError("invalid_auth"), "auth"),
    (ProxyError("proxy returned 401: invalid bearer token"), "auth"),
    (ProxyUnavailableError("connection refused"), "transport"),
    (ProxyError("proxy returned 502: "), "transport"),
    (ProxyError("proxy returned 503: "), "transport"),
    (ProxyError("proxy returned 504: "), "transport"),
    (ProxyError("proxy returned 429: "), "throttle"),
    (ProxyError("proxy returned 403: method not allowed"), "local"),
    (ProxyError("search.messages: page repeated after 1500 records"), "local"),
    (InternalApiError("internal_error"), "upstream"),
    (InternalApiError("channel_not_found"), "entity"),
    (InternalApiError("thread_not_found"), "entity"),
    (InternalApiError("ratelimited"), "throttle"),
    (InternalApiError("missing_scope"), "auth"),
    (slack_error("channel_not_found"), "entity"),
    (slack_error("ratelimited"), "throttle"),
    (slack_error("fatal_error"), "upstream"),
    (KeyError("user_id"), "contract"),
    (ValueError("bad ts"), "contract"),
    (TypeError("None + 1"), "contract"),
    (WalkMismatchError("walked 1 against 100"), "local"),
    (psycopg.OperationalError("connection lost"), "local"),
    (TimeoutError("read timed out"), "transport"),
    (RuntimeError("something else"), "local"),
])
def test_classify_exception_returns_fault_class_name(exc, expected):
    assert faults.classify(exc).name == expected


def test_classes_disposition_raise_for_fatal_classes_continue_for_others():
    for name in ("cancelled", "auth", "transport", "local"):
        assert faults.CLASSES[name]["disposition"] == "raise"
    for name in ("upstream", "contract", "entity", "throttle", "contended"):
        assert faults.CLASSES[name]["disposition"] == "continue"


def test_classify_long_message_truncates_detail_to_limit():
    fault = faults.classify(RuntimeError("x" * 2000))
    assert len(fault.detail) == faults.DETAIL_LIMIT
