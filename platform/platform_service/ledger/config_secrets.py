"""Which values of a plugin configuration are secrets, in a ledger copy.

A secret-named key (key, token, secret, password, credential) holds only whether it is set, and any string
shaped like a known kind of key is replaced too: what the engine's plugin router writes for a plugin it cannot
load. Used to mask the platform's copies of old configuration events (secret_cleanup.py) and to accept the
engine's masked re-send of one as a replay (routes/ledger.py).

Stdlib only. The engine's backend (aisc_backend/config_secrets.py) carries the same rule, and a root test keeps
the copies equal.
"""
from __future__ import annotations

import re

#: What a secret field's value is in a ledger copy: whether it is set, never what it is.
SECRET_SET = "set"

#: A key holding one of these words is a secret in a ledger copy.
LEDGER_SECRET_NAME = re.compile(r"key|token|secret|password|credential", re.IGNORECASE)
#: Strings shaped like a known kind of key, wherever they are.
SECRET_SHAPE = re.compile(
    r"(?i)\bbearer\s+\S+"
    r"|\bsk-[A-Za-z0-9_-]{16,}"
    r"|\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*\.[A-Za-z0-9_-]*"
    r"|\bhf_[A-Za-z0-9]{20,}"
    r"|\bgh[pousr]_[A-Za-z0-9]{20,}"
    r"|\bAKIA[0-9A-Z]{16}\b"
    r"|\bxox[abpr]-[A-Za-z0-9-]{10,}"
    r"|\bAIza[0-9A-Za-z_-]{35}")

_EMPTY = (None, "", [], {})


def _path(prefix: str, name) -> str:
    return f"{prefix}.{name}" if prefix else str(name)


def masked_for_ledger(value):
    """`value` as a ledger copy may hold it: a secret-named key's value is SECRET_SET (None when empty), and any
    string with a key shape is SECRET_SET. Recursive over dicts and lists; anything else is kept."""
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
    if isinstance(value, str) and SECRET_SHAPE.search(value):
        return SECRET_SET
    return value


def _plaintext(value) -> bool:
    return isinstance(value, str) and value != "" and value != SECRET_SET


def plaintext_secret_paths(value, _prefix: str = "") -> list[str]:
    """The paths (`a.b`, `items[0].token`) of the values a ledger copy must not hold: a secret-named key with a
    plain string (or a list holding one), and any string with a key shape. A listed key is not descended into."""
    found: list[str] = []
    if isinstance(value, dict):
        for name, inner in value.items():
            path = _path(_prefix, name)
            if LEDGER_SECRET_NAME.search(str(name)) and (
                    _plaintext(inner) or (isinstance(inner, list) and any(_plaintext(item) for item in inner))):
                found.append(path)
            else:
                found.extend(plaintext_secret_paths(inner, path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(plaintext_secret_paths(item, f"{_prefix}[{index}]"))
    elif isinstance(value, str) and SECRET_SHAPE.search(value):
        found.append(_prefix)
    return found


def holds_plaintext_secret(value) -> bool:
    return bool(plaintext_secret_paths(value))
