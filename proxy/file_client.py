import os
import urllib.error
import urllib.parse
import urllib.request

READ = "files.read"
METHODS = frozenset({READ})

UPSTREAM_TIMEOUT = 30
MAX_BYTES = 12 * 1024 * 1024
SLACK_HOSTS = (".slack.com", ".slack-edge.com")
FALLBACK_TYPE = "application/octet-stream"


class FileError(RuntimeError):
    """Slack would not hand over the file"""


def cookie():
    value = os.environ.get("SLACK_D_COOKIE", "").strip()
    if not value:
        raise FileError("SLACK_D_COOKIE must be set to read a file")
    return value


def hosted_by_slack(url):
    host = urllib.parse.urlparse(url).hostname or ""
    return any(host == one.lstrip(".") or host.endswith(one) for one in SLACK_HOSTS)


def plain_https_address(url):
    try:
        parts = urllib.parse.urlsplit(url)
        return (
            parts.scheme == "https"
            and not parts.username
            and not parts.password
            and parts.port in (None, 443)
        )
    except ValueError:
        return False


class SlackOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if not plain_https_address(target) or not hosted_by_slack(target):
            raise FileError("redirect outside Slack refused")
        return super().redirect_request(req, fp, code, msg, headers, target)


OPENER = urllib.request.build_opener(SlackOnlyRedirects)


def url_of(params):
    url = str(params.get("url") or "").strip()
    if not url:
        raise FileError("url is required")
    if not url.startswith("https://") or not plain_https_address(url):
        raise FileError("file url must be plain https")
    if not hosted_by_slack(url):
        raise FileError("file url is not hosted by Slack")
    return url


def read(params):
    url = url_of(params)
    request = urllib.request.Request(url, headers={"Cookie": f"d={cookie()}"})
    try:
        with OPENER.open(request, timeout=UPSTREAM_TIMEOUT) as response:
            body = response.read(MAX_BYTES + 1)
            content_type = response.headers.get("Content-Type") or FALLBACK_TYPE
    except urllib.error.HTTPError as failure:
        raise FileError(f"Slack returned {failure.code}") from failure
    except urllib.error.URLError as failure:
        raise FileError(f"Slack unreachable: {failure.reason}") from failure

    if len(body) > MAX_BYTES:
        raise FileError(f"file exceeds {MAX_BYTES} bytes")
    if content_type.startswith("text/html"):
        raise FileError("Slack returned a sign-in page")
    return body, content_type
