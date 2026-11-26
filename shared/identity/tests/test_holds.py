"""A save refused because someone else holds the part, or because the task is in check, answers the refusal
object. The wording is one case file, hold-refusal-cases.json, which the TypeScript twin
(shared/access-ts/holds.ts) runs too.
"""
import json
from datetime import datetime
from pathlib import Path

import pytest

from aisc_identity import holds

CASES = json.loads((Path(__file__).parent.parent / "hold-refusal-cases.json").read_text())["cases"]


@pytest.mark.parametrize("case", [pytest.param(c, id=c["name"]) for c in CASES])
def test_a_refused_save_answers_the_refusal_of_its_case(case):
    now = datetime.fromisoformat(case["now"].replace("Z", "+00:00"))
    refusal = holds.refusal_for(case["sqlstate"], json.dumps(case["detail"]) if case["detail"] else None,
                                label=case["label"], person_name=case["person"], now=now)
    assert refusal.as_dict() == case["refusal"]


def test_another_database_error_is_no_refusal():
    assert holds.refusal_for("23505", None, label="Governance", person_name="Luca Bianchi") is None


class _Autocommit:
    autocommit = True

    class info:
        transaction_status = 0


def test_a_claim_outside_a_transaction_is_refused():
    with pytest.raises(holds.NotInTransaction):
        holds.claim_for_save(_Autocommit(), "fill_checklist", "submission-1", "governance", "Governance",
                             "luca-subject", "Luca Bianchi")
