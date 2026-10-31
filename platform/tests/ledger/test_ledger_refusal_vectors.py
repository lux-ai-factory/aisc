"""The platform's canonical JSON against the refusal vectors the emitters share.

fixtures/canonical_refusals.json is read by aisc_identity.ledger_events (shared/identity) and by the
TypeScript emitter (shared/ledger-ts). Each refuses every vector before an event is written; the
platform's canonical JSON refuses those RFC 8785 has no form for and keeps the rest (U+0000 and an
integer-valued double have a form), which is why the emitters check more than canonical JSON.
"""
from __future__ import annotations

import datetime
import json
import math
from pathlib import Path

import pytest

from platform_service.ledger.canonical import canonical

VECTORS = json.loads((Path(__file__).parent / "fixtures" / "canonical_refusals.json").read_text())


@pytest.mark.parametrize("vector", VECTORS["not_ledger_safe"], ids=lambda v: v["name"])
def test_the_platform_refuses_or_keeps_each_vector_as_the_file_says(vector):
    value = json.loads(vector["json"])
    if vector["platform"] == "refuses":
        with pytest.raises((ValueError, TypeError)):
            canonical(value)
    else:
        assert canonical(value)


def _cycle():
    items: list = []
    items.append(items)
    return items


#: The vectors' `values`, as Python builds them. A BigInt has no Python counterpart.
VALUES = {"not_finite": [math.nan, math.inf], "key_not_text": [{1: "a"}],
          "date": [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc)], "bigint": [], "cycle": [_cycle()]}


def test_every_named_value_is_built_here():
    assert set(VECTORS["values"]) == set(VALUES)


@pytest.mark.parametrize("value", [value for values in VALUES.values() for value in values])
def test_what_json_has_no_form_for_is_refused(value):
    # A value that contains itself ends in RecursionError here: refused, if not by name.
    with pytest.raises((ValueError, TypeError, RecursionError)):
        canonical({"v": value})
