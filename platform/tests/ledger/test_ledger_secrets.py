"""K1-K8, phase 1: the ledger's keys and digests (I8, I10, T22; spec 6.1 `secrets`, 7.5).

Per-project, per-purpose keys are derived with HKDF-SHA256 from versioned master keys
(`PLATFORM_LEDGER_KEYS="v1:<hex>,v2:<hex>"`, read on every call). Every digest names its version
(`hmac:v<N>:` + 32 hex); new ones use the newest; a kept version still checks; a retired one doesn't.
"""
from __future__ import annotations

import re

import pytest

from platform_service.ledger import secrets
from platform_service.ledger.canonical import canonical

P1 = "5d3f5f2a-ac34-414b-ae8d-3df80dfe8df3"
P2 = "00000000-0000-4000-8000-0000000000b2"
V1 = "v1:" + "11" * 32
V2 = "v2:" + "22" * 32


@pytest.fixture(autouse=True)
def _keys(monkeypatch):
    monkeypatch.setenv("PLATFORM_LEDGER_KEYS", V1)


def test_a_digest_names_its_version_and_is_32_hex():
    assert re.fullmatch(r"hmac:v1:[0-9a-f]{32}", secrets.digest(P1, "content", b"x"))


def test_keys_differ_per_project_and_per_purpose_and_ignore_the_pids_case():
    assert secrets.derive(P1, "content") != secrets.derive(P2, "content")
    assert secrets.derive(P1, "content") != secrets.derive(P1, "state")
    assert secrets.derive(P1.upper(), "content") == secrets.derive(P1, "content")
    assert secrets.derive(None, "content") != secrets.derive(P1, "content")          # the platform's scope


def test_derivation_is_hkdf_sha256_with_the_specs_info():
    """So another implementation (an auditor's checker) can derive the same key."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    expected = HKDF(algorithm=hashes.SHA256(), length=32, salt=None,
                    info=f"aisc-ledger/content/{P1}".encode()).derive(bytes.fromhex("11" * 32))
    assert secrets.derive(P1, "content") == ("v1", expected)


@pytest.mark.parametrize("purpose", ["", "secret", "Content", None])
def test_an_unknown_purpose_is_refused(purpose):
    with pytest.raises(ValueError):
        secrets.derive(P1, purpose)


def test_the_newest_version_is_used_and_old_ones_still_check(monkeypatch):
    old = secrets.digest(P1, "content", b"x")
    monkeypatch.setenv("PLATFORM_LEDGER_KEYS", f"{V1},{V2}")                  # read on every call
    new = secrets.digest(P1, "content", b"x")
    assert old.startswith("hmac:v1:") and new.startswith("hmac:v2:")
    assert secrets.check(P1, "content", b"x", old) and secrets.check(P1, "content", b"x", new)
    assert not secrets.check(P1, "content", b"y", new)
    assert set(secrets.derive_all(P1, "content")) == {"v1", "v2"}


def test_a_retired_version_no_longer_checks(monkeypatch):
    old = secrets.digest(P1, "content", b"x")
    monkeypatch.setenv("PLATFORM_LEDGER_KEYS", V2)
    assert not secrets.check(P1, "content", b"x", old)


@pytest.mark.parametrize("value", ["", "v1", "v1:zz", "v1:" + "11" * 31, "1:" + "11" * 32,
                                   f"{V1},{V1}", "v0:" + "11" * 32])
def test_a_malformed_key_list_is_refused(monkeypatch, value):
    monkeypatch.setenv("PLATFORM_LEDGER_KEYS", value)
    with pytest.raises(ValueError):
        secrets.digest(P1, "content", b"x")


def test_without_keys_nothing_is_digested(monkeypatch):
    monkeypatch.delenv("PLATFORM_LEDGER_KEYS")
    with pytest.raises(RuntimeError, match="PLATFORM_LEDGER_KEYS"):
        secrets.digest(P1, "content", b"x")


def test_content_and_state_digests_are_canonical_and_apart():
    assert secrets.content_digest(P1, {"b": 1, "a": 2}) == secrets.digest(P1, "content", canonical({"a": 2, "b": 1}))
    assert secrets.state_digest(P1, {"a": 1}) != secrets.content_digest(P1, {"a": 1})
    assert secrets.fingerprint(P1, "sk-abc") == secrets.digest(P1, "fingerprint", b"sk-abc")


def test_a_malformed_digest_never_checks():
    for bad in ["", "hmac:", "hmac:v9:" + "0" * 32, "sha256:" + "0" * 32, "hmac:v1:xyz"]:
        assert not secrets.check(P1, "content", b"x", bad)
