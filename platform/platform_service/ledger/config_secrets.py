"""Which values of a plugin configuration are secrets, in a ledger copy.

A field the plugin's form marks as secret, a value the stored rule takes for a secret (its name, singular or
plural, and its value together) and any string shaped like a known kind of key hold only whether they are set, and a
key assigned inside text (`api_key=...` in a prompt) is redacted there: what the engine writes and sends as its
ledger copy. A name alone hides nothing (`tokens: 512` stays), and numbers and booleans are never hidden. Used to
mask the platform's copies of old configuration events (secret_cleanup.py) and to accept the engine's masked
re-send of one as a replay (routes/ledger.py).

Stdlib only. The engine's backend (aisc_backend/config_secrets.py) carries the same rule, and a root test keeps
the copies equal.
"""
from __future__ import annotations

import re

#: What a secret field's value is in a ledger copy: whether it is set, never what it is.
SECRET_SET = "set"
#: What a key assigned inside text becomes.
REDACTED = "[redacted]"
#: A value under a name ending in key or token is a secret only if it is at least this long, with no whitespace.
WEAK_MIN_LENGTH = 16

#: A value that looks like a credential after `Bearer`, `Basic`, `Token` or a bare `token=`: 16 characters or more
#: of the base64, hex and URL-safe alphabets, no space (`the bearer of bad news`, `token=EOF` are not secrets).
CREDENTIAL = r"[A-Za-z0-9+/=_.~-]{16,}"
#: Strings shaped like a known kind of key, wherever they are: provider key prefixes, JWTs, a credential-shaped
#: `Bearer` value, a credential-shaped `Basic` or `Token` value, bare or in an `Authorization:` header (group 1
#: keeps the header name), the `user:password` of a URL and a whole PEM private-key block. Not caught: a
#: base64-encoded key (other than a Basic value), a key split across lines, a key with no known prefix outside an
#: assignment.
SECRET_SHAPE = re.compile(
    r"(?i)\bbearer\s+" + CREDENTIAL +
    r"|\bsk-[A-Za-z0-9_-]{16,}"
    r"|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*"
    r"|\bhf_[A-Za-z0-9]{20,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bxox[abpr]-[A-Za-z0-9-]{10,}"
    r"|\bAIza[0-9A-Za-z_-]{35}"
    r"|(\bauthorization\s*:\s*)?\b(?:basic|token)\s+" + CREDENTIAL +
    r"|(?<=://)[^/\s:@]+:[^/\s@]+(?=@)"
    r"|-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----[\s\S]*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----")
#: `password=...`, `api_key: "..."`, `api_key%3D...` and the like in text. Group 1 is the name, which may carry
#: any prefix ending in `_` or at a lower-to-upper case step (`judge_api_key`, `DB_PASSWORD`, `judgeApiKey`), but
#: nothing after it (`api_key_env=`, `password_min_length=` are not secrets); group 3 is the value, up to the next
#: whitespace or the closing quote. A bare `token` or `pwd` counts only before `=` (`unexpected token: }` and
#: `pwd: /home` are not secrets). The value is redacted only when it looks like a key (see `_key_like`), so
#: `password: it must contain a digit` stays. Not caught: a value that reads like a word (no digit, and under 16
#: characters or all in one case, such as `password=letmein`), and a quoted value of several words (a multi-word
#: passphrase such as `password = 'correct horse battery staple'`), which reads like prose.
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b((?:[a-z0-9-]*_|[a-z0-9]*(?-i:[a-z0-9])(?=(?-i:[A-Z])))?"
    r"(?:api[_-]?key|apikey|access[_-]?token|auth[_-]?token|refresh[_-]?token|secret[_-]?key"
    r"|(?:aws[_-]?)?secret[_-]?access[_-]?key|client[_-]?secret|password|passwd"
    r"|(?:token|pwd)(?=[\"']?\s*(?:=|%3d))))"
    r"([\"']?\s*(?:[=:]|%3d)\s*[\"']?)"
    r"((?!\[redacted\])(?:(?<=\")[^\"\s]+(?=\")|(?<=')[^'\s]+(?=')|[^\s\"',;]+))")

STRONG_LAST = {"password", "passwd", "passphrase", "secret", "credential", "credentials", "apikey", "authorization",
               "cookie"}
STRONG_PAIRS = {("api", "key"), ("access", "key"), ("private", "key"), ("secret", "key"), ("access", "token"),
                ("auth", "token"), ("api", "token"), ("bearer", "token"), ("refresh", "token"), ("session", "token")}
WEAK_LAST = {"key", "token"}

_WORD_SPLIT = re.compile(r"[^A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")


def _path(prefix: str, name) -> str:
    return f"{prefix}.{name}" if prefix else str(name)


#: A list index in a path (`items[0]`); a form names every item of a list as `items[]`.
_LIST_INDEX = re.compile(r"\[\d+\]")


def _ledger_secret(path: str, name, value, secret_paths: frozenset[str]) -> bool:
    """Whether a ledger copy holds only whether `value` is set: the form marks its path, or the stored rule takes
    it for a secret under its name or under the singular of its last word (`api_keys: {...}`). A number or a
    boolean never is."""
    if _LIST_INDEX.sub("[]", path) in secret_paths:
        return _holds_string(value)
    name = str(name)
    if _stored_secret(stored_secret_name(name), value):
        return True
    singular = name[:-1] if name.lower().endswith("s") else None
    return bool(singular) and _stored_secret(stored_secret_name(singular), value)


def masked_for_ledger(value, secret_paths: frozenset[str] = frozenset(), _prefix: str = ""):
    """`value` as a ledger copy may hold it: a secret field's value (see `_ledger_secret`) is SECRET_SET, a string
    with a key shape is SECRET_SET, and a string with a secret assignment in it (`api_key=...` in a prompt) keeps
    its text with the assigned value redacted. `secret_paths` are the paths the plugin's form marks (`a.b`, and
    `a[].b` inside the items of a list). Recursive over dicts and lists; anything else is kept."""
    if isinstance(value, dict):
        out = {}
        for name, inner in value.items():
            path = _path(_prefix, name)
            if _ledger_secret(path, name, inner, secret_paths):
                out[name] = SECRET_SET
            else:
                out[name] = masked_for_ledger(inner, secret_paths, path)
        return out
    if isinstance(value, list):
        return [masked_for_ledger(item, secret_paths, f"{_prefix}[]") for item in value]
    if isinstance(value, str):
        if SECRET_SHAPE.search(value):
            return SECRET_SET
        return _scrub_assignments(value)
    return value


def plaintext_secret_paths(value, secret_paths: frozenset[str] = frozenset(), _prefix: str = "") -> list[str]:
    """The paths (`a.b`, `items[0].token`) of the values a ledger copy must not hold: a secret field (see
    `_ledger_secret`) whose value is not SECRET_SET, and any string with a key shape or a secret assignment. A
    listed field is not descended into."""
    found: list[str] = []
    if isinstance(value, dict):
        for name, inner in value.items():
            path = _path(_prefix, name)
            if inner != SECRET_SET and _ledger_secret(path, name, inner, secret_paths):
                found.append(path)
            else:
                found.extend(plaintext_secret_paths(inner, secret_paths, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(plaintext_secret_paths(item, secret_paths, f"{_prefix}[{index}]"))
    elif isinstance(value, str) and (SECRET_SHAPE.search(value) or _scrub_assignments(value) != value):
        found.append(_prefix)
    return found


def holds_plaintext_secret(value) -> bool:
    return bool(plaintext_secret_paths(value))


# The stored rule: which names and values are secrets

#: A whole value that is a URL with a user and password in it (`https://user:pass@host/...`).
_URL_WITH_CREDENTIALS = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^/\s:@]+:[^/\s@]+@\S*")


def name_words(name: str) -> list[str]:
    """`judgeApiKey` -> judge, api, key; `hf_token` -> hf, token."""
    words: list[str] = []
    for part in _WORD_SPLIT.split(name):
        words.extend(piece.lower() for piece in _CAMEL.split(part) if piece)
    return words


def stored_secret_name(name: str) -> str | None:
    """"strong" when the name ends in a secret word or pair (header fields such as Authorization and Cookie
    included), "weak" when it ends in key or token, else None."""
    words = name_words(name)
    if not words:
        return None
    if words[-1] in STRONG_LAST or tuple(words[-2:]) in STRONG_PAIRS:
        return "strong"
    if words[-1] in WEAK_LAST:
        return "weak"
    return None


def _holds_string(value) -> bool:
    if isinstance(value, str):
        return value != ""
    if isinstance(value, dict):
        return any(_holds_string(inner) for inner in value.values())
    if isinstance(value, list):
        return any(_holds_string(item) for item in value)
    return False


def _wholly_one_secret(value: str) -> bool:
    """The whole string is one key shape (`sk-...`, `Bearer ...`, a PEM private key) or a URL with credentials: it
    is nothing but a secret, or holds one that no placeholder could stand in for."""
    value = value.strip()
    return SECRET_SHAPE.fullmatch(value) is not None or _URL_WITH_CREDENTIALS.fullmatch(value) is not None


def _stored_secret(kind: str | None, value) -> bool:
    if isinstance(value, dict):
        return kind == "strong" and _holds_string(value)
    if isinstance(value, list):
        if kind == "strong":
            return _holds_string(value)
        return any(_stored_secret(kind, item) for item in value if isinstance(item, str))
    if not isinstance(value, str) or not value:
        return False
    if _wholly_one_secret(value) or kind == "strong":
        return True
    return kind == "weak" and len(value) >= WEAK_MIN_LENGTH and not any(char.isspace() for char in value)



# Keys assigned inside text


_CREDENTIAL_VALUE = re.compile(CREDENTIAL)
_STRONG_TOKEN_NAME = re.compile(r"(?i)(?:access|auth|refresh)[_-]?token$")


def _key_like(name: str, value: str) -> bool:
    """Whether an assigned value looks like a key rather than a word: after a bare `token` it must look like a
    credential (16 characters or more); after any other name it holds a digit, or is 16 characters or more with
    upper- and lower-case letters (`hunter22x` and `wJalrXUtnFEMIK7MDENG` are; `it`, `None`, `/home/runner` are
    not)."""
    if name.lower().endswith("token") and not _STRONG_TOKEN_NAME.search(name):
        return _CREDENTIAL_VALUE.fullmatch(value) is not None
    if any(char.isdigit() for char in value):
        return True
    return len(value) >= 16 and value.lower() != value and value.upper() != value


def _redact_assignment(match: re.Match) -> str:
    if not _key_like(match.group(1), match.group(3)):
        return match.group(0)
    return match.group(1) + match.group(2) + REDACTED


def _scrub_assignments(text: str) -> str:
    return SECRET_ASSIGNMENT.sub(_redact_assignment, text)
