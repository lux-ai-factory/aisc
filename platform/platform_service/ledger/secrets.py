"""The ledger's keys and digests.

Master keys are versioned and kept for ever: `PLATFORM_LEDGER_KEYS="v1:<64 hex>,v2:<64 hex>"`, read
on every call so a new version needs no code change (scripts/secrets.sh --add-ledger-key adds one).
Per project and per purpose, a key is derived with HKDF-SHA256, info `aisc-ledger/<purpose>/<pid in
lowercase>` (or `.../platform` for the platform's own scope), so no derived key opens another project
or another purpose, and an auditor given one project's `content` key can check that project only.

A digest is `hmac:v<N>:` + the first 32 hex of HMAC-SHA256 under the newest version's key; `check`
uses the digest's own version, while that version is kept.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re

from platform_service.ledger.canonical import canonical

PURPOSES = ("content", "state", "query", "mapping", "fingerprint")
_KEY = re.compile(r"v([1-9][0-9]*):([0-9a-f]{64})")
_DIGEST = re.compile(r"hmac:v([1-9][0-9]*):([0-9a-f]{32})")


def _masters() -> dict[str, bytes]:
    raw = os.environ.get("PLATFORM_LEDGER_KEYS")
    if raw is None:
        raise RuntimeError("PLATFORM_LEDGER_KEYS is not set: the ledger can't make or check a digest")
    keys: dict[str, bytes] = {}
    for part in raw.split(","):
        m = _KEY.fullmatch(part.strip())
        if not m:
            raise ValueError("PLATFORM_LEDGER_KEYS must be v<N>:<64 hex>[,v<N>:<64 hex>...]")
        version = f"v{m.group(1)}"
        if version in keys:
            raise ValueError(f"PLATFORM_LEDGER_KEYS names {version} twice")
        keys[version] = bytes.fromhex(m.group(2))
    return keys


def _scope(pid) -> str:
    return "platform" if pid is None else str(pid).lower()


def _hkdf(master: bytes, purpose: str, pid) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                info=f"aisc-ledger/{purpose}/{_scope(pid)}".encode()).derive(master)


def _purpose(purpose) -> str:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown key purpose: {purpose!r}")
    return purpose


def derive(pid, purpose, version: str | None = None) -> tuple[str, bytes]:
    """(version, key) for a project (None: the platform's scope) and purpose; the newest by default."""
    purpose = _purpose(purpose)
    masters = _masters()
    if version is None:
        version = max(masters, key=lambda v: int(v[1:]))
    if version not in masters:
        raise KeyError(version)
    return version, _hkdf(masters[version], purpose, pid)


def derive_all(pid, purpose) -> dict[str, bytes]:
    """Every kept version's key for a project and purpose (what an auditor's export carries)."""
    purpose = _purpose(purpose)
    return {v: _hkdf(m, purpose, pid) for v, m in _masters().items()}


def _mac(key: bytes, value) -> str:
    data = value if isinstance(value, bytes) else str(value).encode()
    return hmac.new(key, data, hashlib.sha256).hexdigest()[:32]


def digest(pid, purpose, value) -> str:
    version, key = derive(pid, purpose)
    return f"hmac:{version}:{_mac(key, value)}"


def check(pid, purpose, value, made: str) -> bool:
    """Whether `made` is the digest of `value` under its own version's key (False if not kept)."""
    m = _DIGEST.fullmatch(made or "")
    if not m:
        return False
    try:
        _, key = derive(pid, purpose, f"v{m.group(1)}")
    except KeyError:
        return False
    return hmac.compare_digest(_mac(key, value), m.group(2))


def content_digest(pid, content) -> str:
    return digest(pid, "content", canonical(content))


def state_digest(pid, state) -> str:
    """Before/after states, under a key that is never exported."""
    return digest(pid, "state", canonical(state))


def fingerprint(pid, value) -> str:
    """A secret's fingerprint: never the value."""
    return digest(pid, "fingerprint", value)
