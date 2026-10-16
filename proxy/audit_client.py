import gzip
import json
import os
import urllib.error
import urllib.parse
import urllib.request

from slack_client import admin_token

DEFAULT_BASE_URL = "https://api.slack.com/audit/v1/"
UPSTREAM_TIMEOUT = 60

LOGS = "audit.logs"
ACTIONS = "audit.actions"
SCHEMAS = "audit.schemas"
METHODS = frozenset({LOGS, ACTIONS, SCHEMAS})

PATHS = {LOGS: "logs", ACTIONS: "actions", SCHEMAS: "schemas"}

QUERY_PARAMS = ("latest", "oldest", "limit", "action", "actor", "entity", "cursor")

MAX_LIMIT = 9999

AUTH_CODES = (401, 403)
REFUSAL_CODES = (400,)


class AuditAuthError(RuntimeError):
    """The token cannot read the audit logs: not org-installed, or the scope is missing"""


class AuditApiError(RuntimeError):
    """The audit endpoint refused for some other reason"""


def base_url():
    return os.environ.get("SLACK_AUDIT_BASE_URL", "").strip() or DEFAULT_BASE_URL


def limit_of(params):
    limit = params.get("limit")
    if limit in (None, ""):
        return None
    try:
        return max(1, min(int(limit), MAX_LIMIT))
    except (TypeError, ValueError) as exc:
        raise AuditApiError(f"limit must be a number, got {limit!r}") from exc


def query_for(params):
    query = {}
    for key in QUERY_PARAMS:
        value = params.get(key)
        if value in (None, ""):
            continue
        query[key] = str(value)

    limit = limit_of(params)
    if limit is not None:
        query["limit"] = str(limit)
    return query


def url_for(method, params):
    path = PATHS[method]
    query = query_for(params) if method == LOGS else {}
    url = urllib.parse.urljoin(base_url(), path)
    return f"{url}?{urllib.parse.urlencode(query)}" if query else url


def body_of(response):
    raw = response.read()
    if response.headers.get("Content-Encoding") == "gzip":
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def call(method, params=None):
    if method not in METHODS:
        raise AuditApiError(f"unknown audit method: {method}")

    token = admin_token()
    if not token:
        raise AuditAuthError("admin token not set")

    request = urllib.request.Request(
        url_for(method, params or {}),
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )

    try:
        with urllib.request.urlopen(request, timeout=UPSTREAM_TIMEOUT) as response:
            return body_of(response)
    except urllib.error.HTTPError as failure:
        detail = (failure.read() or b"").decode("utf-8", "replace")[:500]
        if failure.code in AUTH_CODES:
            raise AuditAuthError(f"audit {failure.code}: {detail}") from failure
        if failure.code in REFUSAL_CODES:
            raise AuditApiError(f"audit {failure.code}: {detail or 'refused'}") from failure
        raise
