"""What the ledger refuses, from the vectors every checker reads.

platform/tests/ledger/fixtures/canonical_refusals.json is also run against the TypeScript emitter
(shared/ledger-ts) and the platform's canonical JSON, so the three cannot drift apart without a test
failing. An event is refused when it is built, in the person's own request, rather than by the
database or the relay later.
"""
from __future__ import annotations

import datetime
import json
import math
from pathlib import Path

import pytest

from aisc_identity import ledger_events as ledger

_FILE = Path(__file__).resolve().parents[3] / "platform/tests/ledger/fixtures/canonical_refusals.json"
if not _FILE.exists():
    pytest.skip("the shared vectors live in the aisc repository's platform tests", allow_module_level=True)
VECTORS = json.loads(_FILE.read_text())


def _cycle_list():
    items: list = []
    items.append(items)
    return items


def _cycle_dict():
    record: dict = {}
    record["self"] = record
    return record


#: Each name in the vectors' `values`, built in Python. A BigInt has no Python counterpart.
VALUES = {
    "not_finite": [math.nan, math.inf, -math.inf],
    "key_not_text": [{1: "a"}, {None: "a"}, {("a",): 1}],
    "date": [datetime.datetime(2026, 1, 1, tzinfo=datetime.timezone.utc), datetime.date(2026, 1, 1)],
    "bigint": [],
    "cycle": [_cycle_list(), _cycle_dict()],
}


def test_every_named_value_is_built_here():
    assert set(VECTORS["values"]) == set(VALUES)


@pytest.mark.parametrize("vector", VECTORS["not_ledger_safe"], ids=lambda v: v["name"])
def test_what_the_ledger_cannot_keep_is_refused(vector):
    with pytest.raises(ledger.NotLedgerSafe):
        ledger.event("x.y", item_type="t", item_id="i", content={"v": json.loads(vector["json"])})


@pytest.mark.parametrize("name, value", [(name, value) for name, values in VALUES.items() for value in values])
def test_what_json_has_no_form_for_is_refused(name, value):
    with pytest.raises(ledger.NotLedgerSafe):
        ledger.event("x.y", item_type="t", item_id="i", details={"v": value})


def test_a_value_seen_twice_is_not_a_cycle():
    shared = {"a": 1}
    ledger.event("x.y", item_type="t", item_id="i", content={"one": shared, "two": [shared, shared]})
