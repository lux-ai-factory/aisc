"""The refusal object: the answer to a save that would replace something the person has not seen.

Its shape is one file, refusal-cases.json, which the TypeScript twin (shared/access-ts) runs too, so the two
cannot disagree on what a refusal looks like without one of them failing.
"""
import dataclasses
import json
from pathlib import Path

import pytest

from aisc_identity.refusal import Refusal

CASES = json.loads((Path(__file__).parent.parent / "refusal-cases.json").read_text())
VALID = [pytest.param(case["refusal"], id=case["name"]) for case in CASES["valid"]]
INVALID = [pytest.param(case["refusal"], id=case["name"]) for case in CASES["invalid"]]


@pytest.mark.parametrize("example", VALID)
def test_a_refusal_goes_out_as_it_came_in(example):
    assert Refusal.from_dict(example).as_dict() == example


@pytest.mark.parametrize("code", [c["code"] for c in CASES["codes"]])
def test_a_refusal_may_carry_each_of_the_codes(code):
    example = {**CASES["valid"][0]["refusal"], "code": code}
    assert Refusal.from_dict(example).as_dict()["code"] == code


@pytest.mark.parametrize("example", INVALID)
def test_what_is_not_a_refusal_is_refused(example):
    with pytest.raises(ValueError):  # the kind of error is not specified
        Refusal.from_dict(example)


def test_a_refusal_cannot_be_changed_once_made():
    refusal = Refusal.from_dict(CASES["valid"][0]["refusal"])
    with pytest.raises(dataclasses.FrozenInstanceError):
        refusal.code = "syncing"


def test_the_token_goes_out_as_a_string():
    refusal = Refusal.from_dict(CASES["valid"][0]["refusal"])
    assert isinstance(refusal.as_dict()["current"]["token"], str)
