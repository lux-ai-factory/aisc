"""L1: canonical JSON (RFC 8785), so the same content always gives the same bytes and the same hash."""
from __future__ import annotations

import hashlib
import math

import pytest

from platform_service.ledger.canonical import canonical, sha256_hex


def test_keys_are_sorted_and_there_is_no_whitespace():
    assert canonical({"b": 2, "a": 1, "c": [3, {"z": 0, "y": 1}]}) == b'{"a":1,"b":2,"c":[3,{"y":1,"z":0}]}'


def test_keys_sort_by_utf16_code_units_and_text_stays_utf8():
    # by UTF-16 code units the emoji (surrogate 0xD83D) comes before U+FB33; by code points it would not
    value = {"\ufb33": 3, "\U0001f600": 2, "\u20ac": 1, "a": 1}
    assert canonical(value) == '{"a":1,"\u20ac":1,"\U0001f600":2,"\ufb33":3}'.encode("utf-8")


def test_the_rfc_8785_example():
    value = {"numbers": [333333333.33333329, 1e30, 4.50, 2e-3, 0.000000000000000000000000001],
             "string": "€$\x0f\nA'B\"\\\\\"/",
             "literals": [None, True, False]}
    expected = r'''{"literals":[null,true,false],"numbers":[333333333.3333333,1e+30,4.5,0.002,1e-27],"string":"€$\u000f\nA'B\"\\\\\"/"}'''
    assert canonical(value) == expected.encode("utf-8")


@pytest.mark.parametrize("number, text", [(1.0, b"1"), (-0.0, b"0"), (1e21, b"1e+21"), (0.1, b"0.1"),
                                          (100, b"100"), (-12.5, b"-12.5"), (1e-7, b"1e-7")])
def test_numbers_take_the_ecmascript_form(number, text):
    assert canonical(number) == text


def test_control_characters_are_escaped_and_slash_is_not():
    assert canonical("a\nb\u001fc/d") == b'"a\\nb\\u001fc/d"'


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_values_json_cannot_hold_are_refused(bad):
    with pytest.raises(ValueError):
        canonical({"x": bad})


def test_keys_must_be_text():
    with pytest.raises((TypeError, ValueError)):
        canonical({1: "a"})


def test_the_hash_is_the_sha256_of_the_canonical_bytes():
    value = {"b": [1, 2], "a": "x"}
    assert sha256_hex(value) == hashlib.sha256(canonical(value)).hexdigest()
    assert sha256_hex({"a": "x", "b": [1, 2]}) == sha256_hex(value)


# version 2 additions (R2.11, R4.1) ------------------------------------------------------------------

import json as _json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

VECTORS = _json.loads((Path(__file__).parent / "fixtures" / "canonical_vectors.json").read_text())["vectors"]


@pytest.mark.parametrize("vector", VECTORS, ids=[v["name"] for v in VECTORS])
def test_the_shared_vectors(vector):
    """The same file is read by the TypeScript twin in phase 5."""
    assert canonical(_json.loads(vector["input_json"])) == vector["canonical"].encode("utf-8")


def test_a_boolean_is_never_a_number():
    assert canonical([True, 1, False, 0]) == b"[true,1,false,0]"


@pytest.mark.parametrize("big", [2 ** 53 + 1, -(2 ** 53) - 1, 10 ** 30])
def test_integers_beyond_two_to_the_53_are_refused(big):
    """The TypeScript twin can't hold them exactly."""
    with pytest.raises(ValueError):
        canonical({"n": big})


@pytest.mark.parametrize("bad", ["\ud800", "a\udfffb"])
def test_lone_surrogates_are_refused(bad):
    with pytest.raises(ValueError):
        canonical({"s": bad})


@pytest.mark.parametrize("bad", [Decimal("1.5"), datetime(2026, 10, 2, tzinfo=timezone.utc), b"bytes", {1, 2}])
def test_types_json_has_no_form_for_are_refused(bad):
    with pytest.raises((TypeError, ValueError)):
        canonical({"x": bad})
