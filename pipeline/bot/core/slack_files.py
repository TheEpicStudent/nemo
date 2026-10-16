import urllib.error
import urllib.request
from urllib.parse import urlparse

from bot.core import blobs

TIMEOUT = 30
MAX_REDIRECTS = 3


class SlackOnlyRedirect(urllib.request.HTTPRedirectHandler):
    max_redirections = MAX_REDIRECTS

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not blobs.slack_url(newurl):
            raise urllib.error.HTTPError(newurl, code, "redirect outside Slack refused", headers, fp)
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None and urlparse(newurl).hostname != urlparse(req.full_url).hostname:
            redirected.remove_header("Authorization")
        return redirected


OPENER = urllib.request.build_opener(SlackOnlyRedirect)


def download(url, token, limit):
    if not blobs.slack_url(url):
        return None, "refused", blobs.NOT_SLACK_URL

    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with OPENER.open(request, timeout=TIMEOUT) as response:
            kind = response.headers.get("Content-Type")
            declared = response.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > limit:
                return None, "too_large", f"{declared} bytes is over the {limit} byte limit"
            body = response.read(limit + 1)
            if len(body) > limit:
                return None, "too_large", f"over the {limit} byte limit"
            state, error = blobs.verdict(response.status, kind, len(body), limit)
            return (body if state == "stored" else None), state, error
    except urllib.error.HTTPError as http_error:
        state, error = blobs.verdict(http_error.code, None, 0, limit)
        return None, state, error
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as network_error:
        return None, "failed", f"could not reach slack: {network_error}"
