"""Which values of a plugin configuration are secrets, in a ledger copy.

A secret-named key (key, token, secret, password, credential, and the header fields authorization and cookie)
holds only whether it is set, any string shaped like a known kind of key is replaced too, and a key assigned inside
text (`api_key=...` in a prompt) is redacted there: what the engine writes and sends as its ledger copy. Used to
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

#: A key holding one of these words is a secret in a ledger copy (`Authorization` and `Cookie` as header fields).
LEDGER_SECRET_NAME = re.compile(r"key|token|secret|password|credential|authorization|cookie", re.IGNORECASE)
#: A value that looks like a credential after `Bearer`, `Basic`, `Token` or a bare `token=`: 16 characters or more
#: of the base64, hex and URL-safe alphabets, no space (`the bearer of bad news`, `token=EOF` are not secrets).
CREDENTIAL = r"[A-Za-z0-9+/=_.~-]{16,}"
#: Strings shaped like a known kind of key, wherever they are: provider key prefixes, JWTs, a credential-shaped
#: `Bearer` value, the credential of an `Authorization:` header (Basic, Token; group 1 keeps the header name), the
#: `user:password` of a URL and a whole PEM private-key block. Not caught: a base64-encoded key (other than a Basic
#: header's), a key split across lines, a key with no known prefix outside an assignment.
SECRET_SHAPE = re.compile(
    r"(?i)\bbearer\s+" + CREDENTIAL +
    r"|\bsk-[A-Za-z0-9_-]{16,}"
    r"|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*"
    r"|\bhf_[A-Za-z0-9]{20,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bxox[abpr]-[A-Za-z0-9-]{10,}"
    r"|\bAIza[0-9A-Za-z_-]{35}"
    r"|(\bauthorization\s*:\s*)(?:basic|token)\s+" + CREDENTIAL +
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

_EMPTY = (None, "", [], {})


def _path(prefix: str, name) -> str:
    return f"{prefix}.{name}" if prefix else str(name)


def masked_for_ledger(value):
    """`value` as a ledger copy may hold it: a secret-named key's value is SECRET_SET (None when empty), a string
    with a key shape is SECRET_SET, and a string with a secret assignment in it (`api_key=...` in a prompt) keeps
    its text with the assigned value redacted. Recursive over dicts and lists; anything else is kept."""
    if isinstance(value, dict):
        out = {}
        for name, inner in value.items():
            if LEDGER_SECRET_NAME.search(str(name)):
                out[name] = SECRET_SET if inner not in _EMPTY else None
            else:
                out[name] = masked_for_ledger(inner)
        return out
    if isinstance(value, list):
        return [masked_for_ledger(item) for item in value]
    if isinstance(value, str):
        if SECRET_SHAPE.search(value):
            return SECRET_SET
        return _scrub_assignments(value)
    return value


def _plaintext(value) -> bool:
    """A plain string other than SECRET_SET, or a dict or list holding one at any depth (the whole value is then
    the secret: `api_keys: {openai: ...}`). A number is not: `max_tokens: 512` has the same form."""
    if isinstance(value, str):
        return value != "" and value != SECRET_SET
    if isinstance(value, dict):
        return any(_plaintext(inner) for inner in value.values())
    if isinstance(value, list):
        return any(_plaintext(item) for item in value)
    return False


def plaintext_secret_paths(value, _prefix: str = "") -> list[str]:
    """The paths (`a.b`, `items[0].token`) of the values a ledger copy must not hold: a secret-named key with a
    plain string, or with a dict or list holding one, and any string with a key shape or a secret assignment. A
    listed key is not descended into."""
    found: list[str] = []
    if isinstance(value, dict):
        for name, inner in value.items():
            path = _path(_prefix, name)
            if LEDGER_SECRET_NAME.search(str(name)) and _plaintext(inner):
                found.append(path)
            else:
                found.extend(plaintext_secret_paths(inner, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(plaintext_secret_paths(item, f"{_prefix}[{index}]"))
    elif isinstance(value, str) and (SECRET_SHAPE.search(value) or _scrub_assignments(value) != value):
        found.append(_prefix)
    return found


def holds_plaintext_secret(value) -> bool:
    return bool(plaintext_secret_paths(value))


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
