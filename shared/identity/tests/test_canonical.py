"""aisc_identity.canonical: the one RFC 8785 canonical JSON that the platform and the engine both hash with,
so a digest the engine computes for a ledger event equals the one the platform computes for the same content."""
from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
VECTORS = json.loads((ROOT / "platform/tests/ledger/fixtures/canonical_vectors.json").read_text())["vectors"]


def _canonical_module():
    try:
        return importlib.import_module("aisc_identity.canonical")
    except ModuleNotFoundError:
        pytest.fail("aisc_identity.canonical does not exist: canonical JSON still lives only in the platform")


def test_the_digest_of_a_value_is_the_sha256_of_its_canonical_bytes():
    module = _canonical_module()
    expected = hashlib.sha256(b'{"a":[1.5,"x"],"b":1}').hexdigest()
    assert module.sha256_of({"b": 1, "a": [1.5, "x"]}) == expected


@pytest.mark.parametrize("vector", VECTORS, ids=[v["name"] for v in VECTORS])
def test_the_shared_vectors_give_the_same_bytes(vector):
    module = _canonical_module()
    assert module.canonical(json.loads(vector["input_json"])) == vector["canonical"].encode("utf-8")


def test_non_finite_numbers_are_refused():
    module = _canonical_module()
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            module.canonical({"score": bad})


def test_the_platform_uses_the_same_function():
    module = _canonical_module()
    sys.path.insert(0, str(ROOT / "platform"))
    try:
        platform_canonical = importlib.import_module("platform_service.ledger.canonical")
    finally:
        sys.path.remove(str(ROOT / "platform"))
    assert platform_canonical.canonical is module.canonical, "the platform keeps a copy of its own"
