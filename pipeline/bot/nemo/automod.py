import logging
import threading

import regex

log = logging.getLogger("bot.nemo")

WORD = "word"
SUBSTRING = "substring"
REGEX = "regex"

FLAG = "flag"

SEARCH_TIMEOUT = 0.05

ACTIVE_WORDS = """
SELECT id, word, match_mode, effect, category_key
FROM fd.automod_words
WHERE active
ORDER BY id
"""

RECORD = """
INSERT INTO fd.automod_matches
    (word_id, word, effect, user_id, channel_id, message_ts, thread_ts, body)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (channel_id, message_ts, word) DO NOTHING
RETURNING id
"""

SET_PERMALINK = "UPDATE fd.automod_matches SET permalink = %s WHERE id = ANY(%s)"

_rules = []
_loaded = False
_lock = threading.Lock()


class WordRule:
    def __init__(self, word_id, word, match_mode, effect, category_key):
        self.word_id = word_id
        self.word = word
        self.match_mode = match_mode
        self.effect = effect
        self.category_key = category_key
        self.pattern = compile_pattern(word, match_mode)

    def matches(self, text):
        if self.pattern is None:
            return False
        try:
            return bool(self.pattern.search(text, timeout=SEARCH_TIMEOUT))
        except TimeoutError:
            log.warning("nemo: automod word %r took too long on a message and was skipped", self.word)
            return False


def compile_pattern(word, match_mode):
    text = (word or "").strip()
    if not text:
        return None
    try:
        if match_mode == REGEX:
            return regex.compile(text, regex.IGNORECASE)
        if match_mode == SUBSTRING:
            return regex.compile(regex.escape(text), regex.IGNORECASE)
        return regex.compile(rf"(?<![0-9A-Za-z]){regex.escape(text)}(?![0-9A-Za-z])", regex.IGNORECASE)
    except regex.error as failure:
        log.warning("nemo: automod word %r does not compile: %s", text, failure)
        return None


def refresh(conn):
    global _loaded
    rules = []
    for row in conn.execute(ACTIVE_WORDS).fetchall():
        rule = WordRule(*row)
        if rule.pattern is not None:
            rules.append(rule)
    with _lock:
        _rules[:] = rules
        _loaded = True
    return len(rules)


def active_rules():
    with _lock:
        return list(_rules) if _loaded else None


def matching_rules(text):
    rules = active_rules()
    if not rules or not text:
        return []
    return [one for one in rules if one.matches(text)]


def record(conn, rule, message):
    return conn.execute(RECORD, (
        rule.word_id, rule.word, rule.effect, message.get("user"), message.get("channel"),
        message.get("ts"), message.get("thread_ts"), message.get("text"),
    )).fetchone()


def link(conn, ids, permalink):
    if not ids or not permalink:
        return 0
    conn.execute(SET_PERMALINK, (permalink, list(ids)))
    return len(ids)
