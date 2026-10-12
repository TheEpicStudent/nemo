import re

UNKNOWN = None

SLACK_DESKTOP = re.compile(r"Slack_SSB/([\d.]+)|Slack/([\d.]+).*Electron", re.IGNORECASE)
SLACK_MOBILE = re.compile(r"\bslack/([\d.]+)\s*\(([^;)]+);\s*([^;)]+)", re.IGNORECASE)
SLACK_SDK = re.compile(
    r"slackclient/([\d.]+)|python-slack-sdk|slack[_/:-]bolt|@slack[/:]", re.IGNORECASE
)
SLACK_IOS = re.compile(r"com\.tinyspeck\.chatlyio(?:\.\w+)?/([\d.]+)", re.IGNORECASE)
HUDDLE = re.compile(r"HuddlePhone/([\d.]+)", re.IGNORECASE)
API_CLIENT = re.compile(r"\bApiApp\b|Slack Ruby Client|\bPython/[\d.]+", re.IGNORECASE)

RUNTIMES = (
    ("Bun", re.compile(r"\bBun/([\d.]+)", re.IGNORECASE)),
    ("Deno", re.compile(r"\bDeno/([\d.]+)", re.IGNORECASE)),
    ("Node", re.compile(r"\bnode(?:\.js)?/v?([\d.]+)", re.IGNORECASE)),
    ("aiohttp", re.compile(r"\baiohttp/([\d.]+)", re.IGNORECASE)),
    ("httpx", re.compile(r"\bpython-httpx/([\d.]+)", re.IGNORECASE)),
    ("requests", re.compile(r"\bpython-requests/([\d.]+)", re.IGNORECASE)),
    ("urllib", re.compile(r"\bPython-urllib/([\d.]+)", re.IGNORECASE)),
    ("curl", re.compile(r"\bcurl/([\d.]+)", re.IGNORECASE)),
    ("Go", re.compile(r"\bGo-http-client/([\d.]+)", re.IGNORECASE)),
    ("okhttp", re.compile(r"\bokhttp/([\d.]+)", re.IGNORECASE)),
    ("axios", re.compile(r"\baxios/([\d.]+)", re.IGNORECASE)),
)

BROWSERS = (
    ("Edge", re.compile(r"Edg(?:e|A|iOS)?/([\d.]+)")),
    ("Opera", re.compile(r"OPR/([\d.]+)")),
    ("Firefox", re.compile(r"(?:Firefox|FxiOS)/([\d.]+)")),
    ("Safari", re.compile(r"Version/([\d.]+).*Safari/")),
    ("Chrome", re.compile(r"(?:CriOS|Chrome)/([\d.]+)")),
)

SYSTEMS = (
    ("iPadOS", re.compile(r"iPad; CPU OS ([\d_]+)")),
    ("iOS", re.compile(r"\biOS ([\d.]+)|i(?:Phone|Pod)[^)]*CPU[^)]*OS ([\d_]+)")),
    ("Android", re.compile(r"Android ([\d.]+)")),
    ("macOS", re.compile(r"Mac OS X ([\d_.]+)")),
    ("Windows", re.compile(r"Windows NT ([\d.]+)")),
    ("Linux", re.compile(r"\bLinux\b")),
)

WINDOWS_NAMES = {"10.0": "10 or 11", "6.3": "8.1", "6.2": "8", "6.1": "7"}


def version(raw):
    return (raw or "").replace("_", ".").strip(".")


def named(family, raw):
    return f"{family} {raw}" if raw else family


def windows(raw):
    normalized = version(raw)
    return named("Windows", WINDOWS_NAMES.get(normalized, normalized))


def system(ua):
    for family, pattern in SYSTEMS:
        match = pattern.search(ua)
        if not match:
            continue
        if family == "Windows":
            return windows(match.group(1))
        raw = next((one for one in match.groups() if one), "")
        return named(family, version(raw))
    return UNKNOWN


def browser(ua):
    for family, pattern in BROWSERS:
        match = pattern.search(ua)
        if match:
            return named(family, version(match.group(1)))
    return UNKNOWN


def app(ua):
    match = SLACK_MOBILE.search(ua)
    if match:
        maker = match.group(2).strip()
        if not maker:
            return "Slack mobile"
        family = "Slack Android" if "android" in ua.lower() else "Slack mobile"
        return named(family, version(match.group(1)))

    match = SLACK_DESKTOP.search(ua)
    if match:
        raw = next((one for one in match.groups() if one), "")
        return named("Slack Desktop", version(raw))

    match = SLACK_IOS.search(ua)
    if match:
        return named("Slack iOS", version(match.group(1)))

    if SLACK_SDK.search(ua):
        return "Slack SDK"

    match = HUDDLE.search(ua)
    if match:
        return named("Slack huddle", version(match.group(1)))

    browser_name = browser(ua)
    if browser_name:
        return browser_name

    for family, pattern in RUNTIMES:
        match = pattern.search(ua)
        if match:
            return named(family, version(match.group(1)))

    return UNKNOWN


def device(ua):
    match = SLACK_MOBILE.search(ua)
    if not match:
        return UNKNOWN
    return match.group(2).strip() or UNKNOWN


def api_client(ua):
    raw = (ua or "").strip()
    if not raw:
        return False
    if SLACK_SDK.search(raw) or API_CLIENT.search(raw):
        return True
    return any(pattern.search(raw) for _family, pattern in RUNTIMES)


def parse(ua):
    raw = (ua or "").strip()
    if not raw:
        return {"ua": UNKNOWN, "ua_app": UNKNOWN, "ua_os": UNKNOWN}

    return {"ua": raw, "ua_app": app(raw), "ua_os": system(raw) or device(raw)}
