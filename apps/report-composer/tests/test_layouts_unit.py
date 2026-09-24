"""Layout logic in Python, no database (report run 2026-09-23: R3.3, R3.5 to R3.9, R3.14, R3.15,
R7.3.2). `report_composer.layouts`."""
import copy

import pytest

from conftest import BLOCK_TYPES, CHOICES, DEFAULT_ORDER, IDS, blk, need

L = "report_composer.layouts"


def choices_for(system_id):
    return lambda block_type: copy.deepcopy(CHOICES.get((system_id, block_type), {}))


def validate(blocks, system_id=IDS["A_V2"]):
    return need(L, "validate_layout")(blocks, block_types=BLOCK_TYPES, choices=choices_for(system_id))


def codes(problems):
    return [p["code"] for p in problems]


# R3.3
def test_r3_3_the_default_block_list():
    blocks = need(L, "default_blocks")(BLOCK_TYPES)
    assert [b["block_type"] for b in blocks] == DEFAULT_ORDER
    by_type = {t["type_id"]: t for t in BLOCK_TYPES}
    for b in blocks:
        assert b["options"] == by_type[b["block_type"]]["default_options"]
    assert len({b["instance_id"] for b in blocks}) == len(blocks)


# R3.5
def test_r3_5_a_valid_layout_has_no_problems():
    assert validate([blk("cover"), blk("free_text", text="x"), blk("dashboard_chart", chart_id=33)]) == []


def test_r3_5_unknown_block_type():
    b = blk("no_such_type")
    problems = validate([b])
    assert codes(problems) == ["unknown_block_type"] and problems[0]["instance_id"] == b["instance_id"]


def test_r3_5_invalid_options_name_the_instance_and_the_pointer():
    b = blk("dashboard_chart", chart_id=33, width=99)
    problems = validate([blk("cover"), b])
    assert codes(problems) == ["invalid_options"]
    assert problems[0]["instance_id"] == b["instance_id"] and problems[0]["pointer"] == "/width"


def test_r3_5_a_required_option_missing():
    b = blk("free_text")
    problems = validate([b])
    assert codes(problems) == ["invalid_options"] and problems[0]["pointer"] in ("/text", "")


# R3.6
@pytest.mark.parametrize("block_type,options,pointer", [
    ("test_results", {"evaluations": [IDS["EVAL_B_V1"]]}, "/evaluations/0"),
    ("test_results", {"evaluations": [IDS["EVAL_A_V1"]]}, "/evaluations/0"),
    ("dashboard_chart", {"chart_id": 35}, "/chart_id"),
    ("control_answers", {"checklists": ["cl-b"]}, "/checklists/0"),
])
def test_r3_6_references_must_be_in_the_choices(block_type, options, pointer):
    b = blk(block_type, **options)
    problems = validate([b])
    assert codes(problems) == ["invalid_reference"]
    assert problems[0]["pointer"] == pointer


def test_r3_6_all_is_not_a_reference():
    assert validate([blk("test_results", evaluations="all"), blk("control_answers", checklists="all")]) == []


# R3.7
def test_r3_7_more_than_50_blocks():
    assert "too_many_blocks" in codes(validate([blk("free_text", text="x") for _ in range(51)]))
    assert validate([blk("free_text", text="x") for _ in range(50)]) == []


def test_r3_7_more_than_10_charts():
    assert "too_many_blocks" in codes(validate([blk("dashboard_chart", chart_id=33) for _ in range(11)]))


def test_r3_7_one_cover_only():
    assert "duplicate_cover" in codes(validate([blk("cover"), blk("cover")]))


# R3.8
def test_r3_8_zero_blocks_is_valid_to_save():
    assert validate([]) == []


# R3.9
def test_r3_9_references_are_checked_against_the_new_version():
    b = blk("test_results", evaluations=[IDS["EVAL_A_V2"]])
    assert validate([b], IDS["A_V2"]) == []
    problems = validate([b], IDS["A_V3"])
    assert codes(problems) == ["invalid_reference"]


def test_r3_9_reset_invalid_sets_the_defaults():
    b = blk("test_results", evaluations=[IDS["EVAL_A_V2"]], show_artifacts=True)
    problems = validate([b], IDS["A_V3"])
    fixed = need(L, "reset_invalid")([b], problems, BLOCK_TYPES)
    assert fixed[0]["options"]["evaluations"] == "all"
    assert fixed[0]["options"]["show_artifacts"] is True      # only the invalid option is reset
    assert fixed[0]["instance_id"] == b["instance_id"]


# R3.14, R7.3.2
def test_r3_14_a_template_carries_no_project_data():
    blocks = [blk("cover", report_title="Mine"), blk("test_results", evaluations=[IDS["EVAL_A_V2"]]),
              blk("dashboard_chart", chart_id=33, width=800), blk("control_answers", checklists=["cl-1"]),
              blk("summary_coverage", links=[{"objective_id": "R1.1", "tests": ["LangBiTe"], "checklists": ["cl-1"]}]),
              blk("free_text", text="Confidential words")]
    t = need(L, "to_template")(blocks, BLOCK_TYPES, keep_text=False)
    assert [x["block_type"] for x in t] == [b["block_type"] for b in blocks]
    assert all(set(x) == {"block_type", "options"} for x in t)          # no instance ids
    opts = [x["options"] for x in t]
    assert opts[0]["report_title"] == "Mine"                            # not a reference: kept
    assert opts[1]["evaluations"] == "all"
    assert "chart_id" not in opts[2] and opts[2]["width"] == 800
    assert opts[3]["checklists"] == "all"
    assert opts[4]["links"] == []
    assert opts[5]["text"] == "[text]"
    assert "Confidential words" not in repr(t) and IDS["EVAL_A_V2"] not in repr(t)


def test_r3_14_keep_text():
    t = need(L, "to_template")([blk("free_text", text="Keep me")], BLOCK_TYPES, keep_text=True)
    assert t[0]["options"]["text"] == "Keep me"


# R3.15
def test_r3_15_a_layout_from_a_template_gets_new_instance_ids():
    template = [{"block_type": "cover", "options": {"report_title": "T"}},
                {"block_type": "free_text", "options": {"text": "[text]"}}]
    a = need(L, "from_template")(template)
    b = need(L, "from_template")(template)
    assert [x["block_type"] for x in a] == ["cover", "free_text"]
    assert a[0]["options"] == {"report_title": "T"}
    assert {x["instance_id"] for x in a}.isdisjoint({x["instance_id"] for x in b})
    a[0]["options"]["report_title"] = "changed"
    assert template[0]["options"]["report_title"] == "T"            # a copy
