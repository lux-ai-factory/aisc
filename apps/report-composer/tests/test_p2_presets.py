"""Part 2, D3.6 to D3.8 on the composer side (10-specs-part2.md R2-D3.6.1, R2-D3.6.2, R2-D3.7.3 to R2-D3.7.5,
R2-D3.8.1 composer constant).

- Imported presets lose every reference option of the source and the answer names each reset (D3.6).
- "Keep texts" recognises the prose options of any block type from its schema (D3.7): walking properties,
  items, prefixItems, additionalProperties and oneOf / anyOf / allOf; `x-aisc-prose` true or false decides,
  otherwise an unconstrained string (no enum, const, pattern, format, maxLength <= 300) is prose.
Unit tests on `presets.from_layout` with fake plugin block types, plus database tests with the v2 fake renderer.
"""
import copy
import json

import pytest

from conftest import IDS, some_template
from v2_fakes import BY_TYPE_V2, clean_presets, client_v2, fake_v2, unique  # noqa: F401

PLACEHOLDER = "Write this section."


# ── R2-D3.8.1 the placeholder is one constant, pinned in the composer ───────

def test_r2_d3_8_1_the_composer_placeholder_constant():
    from report_composer import presets

    assert presets.PLACEHOLDER == "Write this section."


# ── R2-D3.7.3, R2-D3.7.4, R2-D3.7.5 schema-driven prose rule ────────────────

def plugin_type(props, required=(), defaults=None, type_id="auditor_notes"):
    schema = {"type": "object", "properties": {"title": {"type": "string", "maxLength": 200}, **props},
              "additionalProperties": False}
    if required:
        schema["required"] = list(required)
    return {"type_id": type_id, "title": "Auditor notes", "contract_version": 1, "options_schema": schema,
            "default_options": defaults or {}}


def export(options, t, keep_text=False):
    from report_composer import presets

    layout = {"name": "L", "description": "", "blocks": [{"instance_id": "i1", "block_type": t["type_id"],
                                                           "options": copy.deepcopy(options)}]}
    return presets.from_layout(layout, [t], keep_text=keep_text).blocks[0]["options"]


CASES = {
    # name: (schema of option "x", value, expected without Keep texts)
    "no_max_length": ({"type": "string"}, "Client X notes", ""),
    "nullable": ({"type": ["string", "null"], "maxLength": 4000}, "Client X notes", None),
    "annotated_short": ({"type": "string", "maxLength": 100, "x-aisc-prose": True}, "Client X", ""),
    "nested_object": ({"type": "object", "properties": {"note": {"type": "string"},
                                                          "label": {"type": "string", "x-aisc-prose": False}}},
                      {"note": "Client X", "label": "keep-me"}, {"note": "", "label": "keep-me"}),
    "array_items": ({"type": "array", "items": {"type": "string"}}, ["Client X", "Client Y"], []),
    "array_min_items": ({"type": "array", "minItems": 2, "items": {"type": "string"}}, ["A", "B", "C"],
                        [PLACEHOLDER, PLACEHOLDER]),
    "objects_in_array": ({"type": "array", "items": {"type": "object", "properties": {
        "label": {"type": "string", "x-aisc-prose": False}, "note": {"type": "string"}}}},
        [{"label": "a", "note": "Client X"}, {"label": "b", "note": "Client Y"}],
        [{"label": "a", "note": ""}, {"label": "b", "note": ""}]),
    "one_of_string_branch": ({"oneOf": [{"const": "none"}, {"type": "string"}]}, "Client X", ""),
    "any_of_nullable": ({"anyOf": [{"type": "string"}, {"type": "null"}]}, "Client X", None),
    "additional_properties": ({"type": "object", "additionalProperties": {"type": "string"}},
                              {"a": "Client X"}, {"a": ""}),
    "prefix_items": ({"type": "array", "prefixItems": [{"type": "string", "x-aisc-prose": False},
                                                       {"type": "string"}]},
                     ["id-1", "Client X"], ["id-1", ""]),
}


@pytest.mark.parametrize("case", sorted(CASES))
def test_r2_d3_7_3_prose_options_are_dropped_without_keep_texts(case):
    schema, value, expected = CASES[case]
    t = plugin_type({"x": schema})
    assert export({"x": value}, t)["x"] == expected


@pytest.mark.parametrize("case", sorted(CASES))
def test_r2_d3_7_5_prose_options_are_kept_with_keep_texts(case):
    """Compatibility: "Keep texts" keeps every value as written (passes today for every case)."""
    schema, value, _ = CASES[case]
    t = plugin_type({"x": schema})
    assert export({"x": value}, t, keep_text=True)["x"] == value


KEPT = {
    "marked_identifier": ({"type": "string", "x-aisc-prose": False}, "model-id-123"),
    "enum": ({"enum": ["a", "b"]}, "a"),
    "typed_enum": ({"type": "string", "enum": ["a", "b"]}, "b"),
    "const": ({"type": "string", "const": "fixed"}, "fixed"),
    "pattern": ({"type": "string", "pattern": "^[A-Z]+$"}, "ABC"),
    "format": ({"type": "string", "format": "date"}, "2026-09-25"),
    "short_title": ({"type": "string", "maxLength": 300}, "A heading"),
    "under_marked_ancestor": ({"type": "object", "x-aisc-prose": False,
                               "properties": {"inner": {"type": "string"}}}, {"inner": "kept"}),
    "one_of_value_matching_a_non_prose_branch": ({"oneOf": [{"const": "none"}, {"type": "string"}]}, "none"),
}


@pytest.mark.parametrize("case", sorted(KEPT))
def test_r2_d3_7_3_identifiers_enums_patterns_are_kept(case):
    """Compatibility guard for most cases (today's rule keeps them too); pins the rule's "never prose" side."""
    schema, value = KEPT[case]
    t = plugin_type({"x": schema})
    assert export({"x": value}, t)["x"] == value


def test_r2_d3_7_3_a_string_under_a_reference_option_is_not_prose():
    t = plugin_type({"source": {"type": "string", "x-aisc-reference": True}},
                    defaults={"source": "latest"})
    assert export({"source": "some-project-id"}, t)["source"] == "latest"   # reset by R-V1.4, not blanked


def test_r2_d3_7_4_a_required_prose_value_becomes_the_placeholder_cut_to_max_length():
    t = plugin_type({"summary": {"type": "string"}, "short": {"type": "string", "x-aisc-prose": True,
                                                              "maxLength": 5},
                     "min": {"type": "string", "minLength": 1}}, required=("summary", "short"))
    got = export({"summary": "Client X", "short": "abc", "min": "Client Y"}, t)
    assert got == {"summary": PLACEHOLDER, "short": PLACEHOLDER[:5], "min": PLACEHOLDER}


def test_r2_d3_7_4_a_value_of_the_wrong_shape_is_left_as_it_is():
    t = plugin_type({"x": {"type": "object", "properties": {"note": {"type": "string"}}}})
    assert export({"x": "a string where an object is expected"}, t)["x"] == "a string where an object is expected"


def test_r2_d3_7_4_titles_stay():
    t = plugin_type({"notes": {"type": "string"}})
    assert export({"title": "Kept heading", "notes": "Client X"}, t) == {"title": "Kept heading", "notes": ""}


def test_r2_d3_7_3_without_a_description_the_fixed_list_applies():
    """Compatibility: a block type the renderer does not describe keeps the fixed list (commentary,
    free_text.text, chapter.intro) and leaves other options alone (passes today)."""
    from report_composer import presets

    layout = {"name": "L", "blocks": [{"block_type": "gone_plugin", "options": {"notes": "Client X",
                                                                               "commentary": "aside"}},
                                      {"block_type": "chapter", "options": {"title": "C", "intro": "Client X"}}]}
    blocks = presets.from_layout(layout, []).blocks
    assert blocks[0]["options"] == {"notes": "Client X", "commentary": ""}
    assert blocks[1]["options"] == {"title": "C", "intro": ""}


# ── R2-D3.6.1, R2-D3.6.2 imported presets lose the source's references ──────

db = pytest.mark.db


def preset_file(blocks, **over):
    doc = {"format": "aisc-report-preset", "version": 1, "name": unique("Carried"), "description": "",
           "toc": "auto", "numbering": False, "blocks": blocks}
    doc.update(over)
    return doc


FOREIGN = [{"block_type": "cover", "options": {}},
           {"block_type": "dashboard_chart", "options": {"chart_id": 991}},
           {"block_type": "test_results", "options": {"evaluations": ["e0000000-0000-4000-8000-00000000dead"]}},
           {"block_type": "changes_since", "options": {"compare_to": "a9000000-0000-4000-8000-000000000009"}}]


def label(type_id, option):
    return BY_TYPE_V2[type_id]["options_schema"]["properties"][option]["title"]


@db
@pytest.mark.usefixtures("clean_layouts", "clean_presets")
def test_r2_d3_6_1_import_stores_no_reference_of_the_source(client_v2, auth):
    r = client_v2.post("/api/presets/import", json=preset_file(FOREIGN), headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    exported = client_v2.get(f"/api/presets/{r.json()['id']}/export", headers=auth("alice")).json()
    chart, tests, changes = (b["options"] for b in exported["blocks"][1:])
    assert "chart_id" not in chart
    assert tests.get("evaluations", "all") == "all"
    assert changes.get("compare_to", "previous") == "previous"
    text = json.dumps(exported["blocks"])      # the name holds a time stamp that may contain "991"
    assert "991" not in text and "dead" not in text and "a9000000" not in text


@db
@pytest.mark.usefixtures("clean_layouts", "clean_presets")
def test_r2_d3_6_2_import_names_every_reset_reference(client_v2, auth):
    r = client_v2.post("/api/presets/import", json=preset_file(FOREIGN), headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    tail = "pointed at data of another project or platform; it was reset to its default."
    assert r.json().get("notices") == [
        {"pointer": "/blocks/1/chart_id", "message": f"The {label('dashboard_chart', 'chart_id')} of block 2 {tail}"},
        {"pointer": "/blocks/2/evaluations", "message": f"The {label('test_results', 'evaluations')} of block 3 {tail}"},
        {"pointer": "/blocks/3/compare_to", "message": f"The {label('changes_since', 'compare_to')} of block 4 {tail}"}]


@db
@pytest.mark.usefixtures("clean_layouts", "clean_presets")
def test_r2_d3_6_2_a_layout_from_a_preset_file_names_every_reset_reference(client_v2, auth):
    body = {"name": unique("From file"), "system_id": IDS["A_V2"], "template_id": some_template(client_v2, auth),
            "preset_file": preset_file(FOREIGN[:3])}
    r = client_v2.post("/api/p/alpha/layouts", json=body, headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    tail = "pointed at data that is not in this project; it was reset to its default."
    assert r.json().get("notices") == [
        {"pointer": "/blocks/1/chart_id", "message": f"The {label('dashboard_chart', 'chart_id')} of block 2 {tail}"},
        {"pointer": "/blocks/2/evaluations", "message": f"The {label('test_results', 'evaluations')} of block 3 {tail}"}]


@db
@pytest.mark.usefixtures("clean_layouts", "clean_presets")
def test_r2_d3_6_2_no_notice_when_nothing_was_reset(client_v2, auth):
    """Compatibility guard: a file without references gives no notice (passes today: no `notices` key)."""
    r = client_v2.post("/api/presets/import", json=preset_file([{"block_type": "cover", "options": {}},
                                                                {"block_type": "test_results",
                                                                 "options": {"evaluations": "all"}}]),
                       headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert r.json().get("notices", []) == []

# The composer showing these notices to the user is a browser test: test_p2_browser.py,
# test_r2_d3_6_2_the_composer_shows_notices_as_information (fix round 1 of part 2, finding 2).
