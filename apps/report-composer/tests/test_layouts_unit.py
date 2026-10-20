"""Layout logic in Python, no database: `report_composer.layouts`."""
import copy

import pytest

from conftest import BLOCK_TYPES, CHOICES, IDS, blk, need

L = "report_composer.layouts"


def choices_for(system_id):
    return lambda block_type: copy.deepcopy(CHOICES.get((system_id, block_type), {}))


def validate(blocks, system_id=IDS["A_V2"]):
    return need(L, "validate_layout")(blocks, block_types=BLOCK_TYPES, choices=choices_for(system_id))


def codes(problems):
    return [p["code"] for p in problems]


def test_a_valid_layout_has_no_problems():
    assert validate([blk("cover"), blk("free_text", text="x"), blk("dashboard_chart", chart_id=33)]) == []


def test_unknown_block_type():
    b = blk("no_such_type")
    problems = validate([b])
    assert codes(problems) == ["unknown_block_type"] and problems[0]["instance_id"] == b["instance_id"]


def test_invalid_options_name_the_instance_and_the_pointer():
    b = blk("dashboard_chart", chart_id=33, width=99)
    problems = validate([blk("cover"), b])
    assert codes(problems) == ["invalid_options"]
    assert problems[0]["instance_id"] == b["instance_id"] and problems[0]["pointer"] == "/width"


def test_a_required_option_missing():
    b = blk("free_text")
    problems = validate([b])
    assert codes(problems) == ["invalid_options"] and problems[0]["pointer"] in ("/text", "")


@pytest.mark.parametrize("block_type,options,pointer", [
    ("test_results", {"evaluations": [IDS["EVAL_B_V1"]]}, "/evaluations/0"),
    ("test_results", {"evaluations": [IDS["EVAL_A_V1"]]}, "/evaluations/0"),
    ("dashboard_chart", {"chart_id": 35}, "/chart_id"),
    ("control_answers", {"checklists": ["cl-b"]}, "/checklists/0"),
])
def test_references_must_be_in_the_choices(block_type, options, pointer):
    b = blk(block_type, **options)
    problems = validate([b])
    assert codes(problems) == ["invalid_reference"]
    assert problems[0]["pointer"] == pointer


def test_all_is_not_a_reference():
    assert validate([blk("test_results", evaluations="all"), blk("control_answers", checklists="all")]) == []


def test_more_than_50_blocks():
    assert "too_many_blocks" in codes(validate([blk("free_text", text="x") for _ in range(51)]))
    assert validate([blk("free_text", text="x") for _ in range(50)]) == []


def test_more_than_10_charts():
    assert "too_many_blocks" in codes(validate([blk("dashboard_chart", chart_id=33) for _ in range(11)]))


def test_one_cover_only():
    assert "duplicate_cover" in codes(validate([blk("cover"), blk("cover")]))


def test_zero_blocks_is_valid_to_save():
    assert validate([]) == []


def test_references_are_checked_against_the_new_version():
    b = blk("test_results", evaluations=[IDS["EVAL_A_V2"]])
    assert validate([b], IDS["A_V2"]) == []
    problems = validate([b], IDS["A_V3"])
    assert codes(problems) == ["invalid_reference"]
