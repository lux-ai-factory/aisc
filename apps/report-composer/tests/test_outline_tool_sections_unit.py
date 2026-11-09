"""A section that prints as one numbered section per chosen tool (an option marked `x-aisc-section-per-choice`, the
Exported results block's `dashboards`): the outline lists the tools under the section's row, numbered as the report
numbers them, and the sections after it take the numbers after the tools. `report_composer.layouts`, no database."""
import pytest

from conftest import blk, need
from test_outline_numbers_unit import _renderer_plan

L = "report_composer.layouts"
EXPORTS_TYPE = {"type_id": "superset_exports", "options_schema": {"type": "object", "properties": {
    "dashboards": {"x-aisc-reference": True, "x-aisc-section-per-choice": True,
                   "oneOf": [{"const": "all"}, {"type": "array", "items": {"type": "string"}}]},
    "comments": {"type": "object", "x-aisc-per-choice-of": "dashboards"}}}}
CHOICES = {"superset_exports": {"dashboards": [{"value": "12", "label": "LangBiTe (Mijke)"},
                                               {"value": "14", "label": "StrongREJECT (Mijke)"}]}}


def exports(dashboards="all"):
    return blk("superset_exports", dashboards=dashboards)


def parts_of(blocks, choices=CHOICES, types=(EXPORTS_TYPE,)):
    return need(L, "section_parts")(blocks, types, choices)


def test_all_gives_every_tool_in_the_order_offered():
    b = exports()
    assert parts_of([blk("cover"), b]) == {b["instance_id"]: ["LangBiTe (Mijke)", "StrongREJECT (Mijke)"]}


def test_a_list_gives_the_tools_it_names_in_the_order_offered():
    b = exports(["14", "99"])
    assert parts_of([b]) == {b["instance_id"]: ["StrongREJECT (Mijke)"]}


def test_no_tool_or_no_choice_gives_no_parts():
    a, b = exports([]), exports()
    assert parts_of([a]) == {}
    assert parts_of([b], choices={}) == {}
    assert parts_of([blk("ai_card")]) == {}


def test_the_tools_are_numbered_under_the_chapter_and_the_next_section_follows_them():
    ch, b, after = blk("chapter", title="Tests"), exports(), blk("ai_card")
    blocks = [blk("cover"), blk("ai_card"), ch, b, after]
    parts = parts_of(blocks)
    got = need(L, "outline")(blocks, (EXPORTS_TYPE,), numbering=True, parts=parts)
    assert [o["number"] for o in got] == ["", "1", "2", "", "2.3"]
    assert got[3]["parts"] == [{"title": "LangBiTe (Mijke)", "number": "2.1"},
                               {"title": "StrongREJECT (Mijke)", "number": "2.2"}]
    assert "parts" not in got[4]
    assert need(L, "outline_numbers")(blocks, numbering=True, parts=parts) == ["", "1", "2", "", "2.3"]


def test_without_numbering_the_tools_are_listed_without_numbers():
    b = exports()
    got = need(L, "outline")([b], (EXPORTS_TYPE,), numbering=False, parts=parts_of([b]))
    assert got[0]["parts"] == [{"title": "LangBiTe (Mijke)", "number": ""},
                               {"title": "StrongREJECT (Mijke)", "number": ""}]


def test_without_parts_the_section_is_numbered_as_one():
    b = exports([])
    assert need(L, "outline_numbers")([blk("ai_card"), b, blk("ai_card")], numbering=True,
                                      parts=parts_of([b])) == ["1", "2", "3"]


@pytest.mark.parametrize("dashboards", ["all", ["14"], []])
def test_the_composer_numbers_the_tools_as_the_renderer_does(dashboards):
    """The renderer makes one section per tool (its document.py _sections_of) before it numbers them."""
    plan = _renderer_plan()
    b = exports(dashboards)
    blocks = [blk("cover"), blk("chapter", title="C"), blk("ai_card"), b, blk("ai_card"), blk("appendix"),
              blk("ai_card")]
    parts = parts_of(blocks)
    sections = []
    for x in blocks:
        kind = x["block_type"] if x["block_type"] in ("chapter", "appendix") else None
        titles = parts.get(x["instance_id"]) or [None]
        sections += [{"instance_id": (x["instance_id"], n), "type_id": x["block_type"], "kind": kind}
                     for n, _ in enumerate(titles)]
    plan(sections, toc="on", numbering=True)
    want = [s["number"] for s in sections]
    got = need(L, "outline")(blocks, (EXPORTS_TYPE,), numbering=True, parts=parts)
    composer = []
    for o in got:
        composer += [p["number"] for p in o["parts"]] if o.get("parts") else [o["number"]]
    assert composer == want
