"""The one secret rule of every Python service: which values are secrets, and how text is cleared of them.

Held to shared vectors, redaction-cases.json beside this package; the copies that cannot import it (the
qualification agents, the plugin publisher, the plugin interface) run the same vectors in their own suites.

Three rules, because the cost of a wrong guess differs:

- Ledger copies (`masked_for_ledger`): a field the plugin's form marks as secret, a value the stored rule below
  takes for a secret (its name, singular or plural, and its value together), and any string shaped like a known
  key hold only whether they are set; a key assigned inside text (`api_key=...` in a prompt) is redacted there.
  A name alone hides nothing: `tokens: 512` and `stop_token: "END"` stay readable, so the ledger says how a run
  was configured. Numbers and booleans are never hidden.
- Stored configurations (`stored_secret_changes`, `without_stored_secrets`): narrow. Only the last word or two of
  a name count, and a `key` or `token` value must look like one; a value that is wholly one key shape or a URL
  with credentials goes whatever its name. A secret field is dropped, never replaced by a placeholder the plugin
  would run with. Free text is never rewritten unless asked: a text field that may hold a key is listed for
  review.
- Text (`scrub_text`, `without_known_bytes`, `shown_error`, `without_forms`): the values a caller knows it
  handed out, then the key shapes, then the key-like value of a `password=...` style assignment.

What the shape rule does not catch: a base64-encoded key (other than a Basic value), a key split across lines,
a key with no known prefix outside an assignment.

Stdlib only.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.parse
from typing import Iterable

#: What a secret field's value is in a ledger copy: whether it is set, never what it is.
SECRET_SET = "set"
#: What a secret in text becomes.
REDACTED = "[redacted]"
#: A known secret shorter than this is never searched for (it would match ordinary words).
MIN_KNOWN_LENGTH = 8
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


# Ledger copies


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


# Stored configurations

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


def stored_secret_changes(config, scrub_config_text: bool = False):
    """(the configuration without its stored secrets, the dropped paths, the text fields to review).

    A field is dropped, never replaced, when its value is a non-empty string (or a dict or list holding one) under
    a strong name, a key-like string under a weak one, or a string that is wholly one key shape or a URL with
    credentials whatever its name. Free text is an input the plugin runs with, so it is never rewritten by default:
    a kept text field in which the text rule finds something (a key pasted into a prompt, or prose that only looks
    like one) is listed for review and left as it is. With `scrub_config_text` those fields are scrubbed in place
    (and still listed)."""
    return _stored_changes(config, "", scrub_config_text)


def _stored_changes(config, prefix: str, scrub: bool):
    if isinstance(config, dict):
        out, dropped, review = {}, [], []
        for name, inner in config.items():
            path = _path(prefix, name)
            if _stored_secret(stored_secret_name(str(name)), inner):
                dropped.append(path)
                continue
            out[name], below, flagged = _stored_changes(inner, path, scrub)
            dropped.extend(below)
            review.extend(flagged)
        return out, dropped, review
    if isinstance(config, list):
        out, dropped, review = [], [], []
        for index, item in enumerate(config):
            new, below, flagged = _stored_changes(item, f"{prefix}[{index}]", scrub)
            out.append(new)
            dropped.extend(below)
            review.extend(flagged)
        return out, dropped, review
    if isinstance(config, str) and prefix:
        text = scrub_text(config)
        if text == config:
            return config, [], []
        return (text if scrub else config), [], [prefix]
    return config, [], []


def without_stored_secrets(config):
    """(the configuration without its stored secrets, the dropped paths). Text fields are left as they are."""
    new, dropped, _ = stored_secret_changes(config)
    return new, dropped


# Text


def _ordered_known(known: Iterable[str]) -> list[str]:
    values = {value for value in known if isinstance(value, str) and len(value) >= MIN_KNOWN_LENGTH}
    return sorted(values, key=lambda value: (-len(value), value))


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


def _redact_shape(match: re.Match) -> str:
    return (match.group(1) or "") + REDACTED


def _redact_assignment(match: re.Match) -> str:
    if not _key_like(match.group(1), match.group(3)):
        return match.group(0)
    return match.group(1) + match.group(2) + REDACTED


def _scrub_assignments(text: str) -> str:
    return SECRET_ASSIGNMENT.sub(_redact_assignment, text)


def scrub_text(text: str, known: Iterable[str] = ()) -> str:
    """`text` with each known value (8 characters or more, longest first), each key shape and the key-like value of
    each secret assignment replaced by REDACTED."""
    for value in _ordered_known(known):
        text = text.replace(value, REDACTED)
    text = SECRET_SHAPE.sub(_redact_shape, text)
    return _scrub_assignments(text)


def without_known_bytes(content: bytes, known: Iterable[str]) -> bytes:
    """`content` with each known value (8 characters or more, longest first), encoded as UTF-8, replaced
    by REDACTED in the raw bytes. Exact values only: no key shapes (a file is evidence, and the shape
    rules rewrite prose) and no encoded forms. It works on any file, but a compressed one (xlsx, png,
    zip) keeps whatever its compression hides."""
    for value in _ordered_known(known):
        content = content.replace(value.encode(), REDACTED.encode())
    return content


# The values under secret-named keys

#: The strings under a key holding one of these words are values a caller scrubs from failure text
#: (`Authorization` and `Cookie` as header fields). Broad on purpose: a value shorter than MIN_KNOWN_LENGTH is
#: never searched for.
LEDGER_SECRET_NAME = re.compile(r"key|token|secret|password|credential|authorization|cookie", re.IGNORECASE)


def secret_named_values(value, out: list[str]) -> None:
    """Every string under a secret-named key of `value`, at any depth, appended to `out`."""
    if isinstance(value, dict):
        for name, inner in value.items():
            if LEDGER_SECRET_NAME.search(str(name)):
                _strings(inner, out)
            else:
                secret_named_values(inner, out)
    elif isinstance(value, list):
        for item in value:
            secret_named_values(item, out)


def _strings(value, out: list[str]) -> None:
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, dict):
        for inner in value.values():
            _strings(inner, out)
    elif isinstance(value, list):
        for item in value:
            _strings(item, out)


# An error as a reader may see it

#: The older, blunter rule an error shown to a reader had before the text rule, kept so nothing it took out
#: comes back: any `key=` or `token:` value, a short `sk-` key, any long run of letters and digits.
_SHOWN_ERROR_EXTRA = (
    # `Bearer <token>`, `Basic <credentials>`
    (re.compile(r"(?i)\b(bearer|basic)\s+(?!\[redacted\])[^\s,;]+"), r"\1 " + REDACTED),
    # `key=...`, `api_key: ...`, `token=...`, `password=...` and the like
    (re.compile(r"(?i)\b([a-z_-]*(?:key|token|secret|password|passwd|pwd|signature|sig|auth|authorization"
                r"|credentials?))(\s*[=:]\s*)(?!\[redacted\])[^\s&,;]+"),
     r"\1\2" + REDACTED),
    # `scheme://user:password@host`
    (re.compile(r"://(?!\[redacted\]@)[^/\s:@]+:[^/\s@]+@"), "://" + REDACTED + "@"),
    # the providers' own key shapes: sk-..., xai-..., gsk_..., hf_..., AIza...
    (re.compile(r"\b(?:sk|pk|rk|xai|gsk|hf|ghp|glpat)[-_][A-Za-z0-9_-]{8,}"), REDACTED),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{10,}"), REDACTED),
    # any other long run of letters and digits together
    (re.compile(r"\b(?=[A-Za-z0-9_-]*\d)(?=[A-Za-z0-9_-]*[A-Za-z])[A-Za-z0-9_-]{32,}"), REDACTED),
)
_WHITESPACE = re.compile(r"\s+")


def shown_error(text: str, limit: int) -> str:
    """`text` as a reader may see it: on one line, key-like parts taken out, at most `limit` characters.

    The text is cut to 4 x `limit` before it is scrubbed, since nothing past the final cut is shown (the
    patterns are super-quadratic on long input). A word that first cut splits is dropped whole, so no half of a
    key escapes its pattern. The key shapes and assignments of the text rule go first (no known values), then
    the older, blunter rule."""
    first, text = 4 * limit, text or ""
    out = _WHITESPACE.sub(" ", text[:first]).strip()
    if len(text) > first and " " in out:
        out = out.rsplit(" ", 1)[0]
    out = SECRET_SHAPE.sub(_redact_shape, out)
    out = SECRET_ASSIGNMENT.sub(_redact_assignment, out)
    for pattern, replacement in _SHOWN_ERROR_EXTRA:
        out = pattern.sub(replacement, out)
    return out if len(out) <= limit else out[: limit - 3].rstrip() + "..."


# A known value as a system may echo it

#: What a known value echoed back by a system becomes.
ECHO_MARK = "***"


def secret_forms(secrets) -> list[str]:
    """Each secret value as a system may echo it: as it is, base64 (standard and URL-safe), URL-encoded
    (with and without "/" kept, and with "+" for spaces) and JSON-escaped; the longest first. No other form:
    not hex, unpadded base64, double encodings or case changes, and a secret split across output items or
    calls is missed; the target must not echo credentials, the scrub is a safety net, not a guarantee."""
    forms = set()
    for value in (v for v in secrets or [] if v):
        raw = value.encode()
        forms.update((value, base64.b64encode(raw).decode(), base64.urlsafe_b64encode(raw).decode(),
                      urllib.parse.quote(value, safe=""), urllib.parse.quote(value),
                      urllib.parse.quote_plus(value), json.dumps(value)[1:-1]))
    return sorted(forms, key=len, reverse=True)


def without_forms(value, forms: list[str], mark: str = ECHO_MARK):
    """`value` with every one of `forms` replaced by `mark`, in a string or, recursively, in the keys and
    values of a dict and the items of a list or tuple (a tuple becomes a list); anything else as it is."""
    if isinstance(value, str):
        for form in forms:
            value = value.replace(form, mark)
        return value
    if isinstance(value, dict):
        return {without_forms(k, forms, mark): without_forms(v, forms, mark) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [without_forms(v, forms, mark) for v in value]
    return value
