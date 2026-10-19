import os
import urllib.error
import urllib.parse
import urllib.request

READ = "files.read"
METHODS = frozenset({READ})

UPSTREAM_TIMEOUT = 30
MAX_BYTES = 12 * 1024 * 1024
FILE_HOST = "files.slack.com"
FILE_PATHS = ("/files-pri/", "/files-tmb/")
CDN_HOST_SUFFIXES = (".slack-edge.com", ".slack-files.com")
MAX_REDIRECTS = 3
COOKIE_HEADER = "Cookie"
FALLBACK_TYPE = "application/octet-stream"


class FileError(RuntimeError):
    """Slack would not hand over the file"""


def cookie():
    value = os.environ.get("SLACK_D_COOKIE", "").strip()
    if not value:
        raise FileError("SLACK_D_COOKIE must be set to read a file")
    return value


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


def file_address(url):
    if not plain_https_address(url):
        return False
    parts = urllib.parse.urlsplit(url)
    path = urllib.parse.unquote(parts.path)
    return (
        (parts.hostname or "").lower() == FILE_HOST
        and path.startswith(FILE_PATHS)
        and not {"..", "."} & set(path.split("/"))
    )


def cdn_address(url):
    if not plain_https_address(url):
        return False
    return (urllib.parse.urlsplit(url).hostname or "").lower().endswith(CDN_HOST_SUFFIXES)


class SlackOnlyRedirects(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if not file_address(target) and not cdn_address(target):
            raise FileError("redirect outside Slack refused")
        redirected = super().redirect_request(req, fp, code, msg, headers, target)
        if redirected is not None and not file_address(target):
            redirected.remove_header(COOKIE_HEADER)
        return redirected


OPENER = urllib.request.build_opener(SlackOnlyRedirects)


def url_of(params):
    url = str(params.get("url") or "").strip()
    if not url:
        raise FileError("url is required")
    if not url.startswith("https://") or not plain_https_address(url):
        raise FileError("file url must be plain https")
    if not file_address(url):
        raise FileError("file url is not a Slack file")
    return url


def read(params):
    url = url_of(params)
    request = urllib.request.Request(url, headers={COOKIE_HEADER: f"d={cookie()}"})
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
