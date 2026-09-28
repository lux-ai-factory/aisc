"""V1: reusable report structures (report run v2, 01-specs.md section 2: R-V1.1 to R-V1.12).

Report modules 2026-09-28: the preset library and "Start from" are gone; a structure is reused by
duplicating a layout or by exporting it as a file (format aisc-report-preset, version 2; version 1 is
still read) and importing that file as a layout. The built-in layouts are tested in test_rm_builtins.py.
Database tests on the composer bed, with the v2 fake renderer (v2_fakes.py).
"""
import json
from pathlib import Path

import pytest

from conftest import IDS, error_code, new_layout, some_template
from v2_fakes import clean_presets, client_v2, fake_v2, unique, scalar_json, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts", "clean_presets")]

PRESETS_DIR = Path(__file__).resolve().parents[1] / "report_composer/presets"
def preset_file(blocks, name="Carried structure", **over):
    doc = {"format": "aisc-report-preset", "version": 1, "name": name, "description": "",
           "toc": "auto", "numbering": False, "blocks": blocks}
    doc.update(over)
    return doc


def create(client, auth, who="alice", slug="alpha", **body):
    body.setdefault("name", unique("Layout"))
    if "template_id" not in body:
        body["template_id"] = some_template(client, auth, slug=slug, who=who)
    return client.post(f"/api/p/{slug}/layouts", json=body, headers=auth(who))


# ── R-V1.1 built-in presets: replaced by the five built-in layouts (test_rm_builtins.py) ──

# ── R-V1.2, R-V1.3 creating a layout from a preset ───────────────────────────

@pytest.mark.parametrize("extra", [
    {"file": {"format": "aisc-report-preset", "version": 2, "name": "x", "blocks": []}, "blocks": []},
    {"preset_file": {"format": "aisc-report-preset", "version": 1, "name": "x", "blocks": []}, "blocks": []},
])
def test_r_v1_3_at_most_one_source_of_blocks(client_v2, auth, extra):
    r = create(client_v2, auth, **extra)
    assert r.status_code == 422 and error_code(r) == "invalid_request"


def test_r_v1_3_a_layout_from_a_preset_file_takes_its_name_from_the_file(client_v2, auth):
    doc = preset_file([{"block_type": "cover", "options": {"report_title": "Carried"}},
                       {"block_type": "free_text", "options": {"text": "x"}}], name="Carried structure",
                      toc="on", numbering=True)
    body = {"template_id": some_template(client_v2, auth), "preset_file": doc}
    r = client_v2.post("/api/p/alpha/layouts", json=body, headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert r.json()["name"] == "Carried structure"
    assert (r.json().get("show_index"), r.json().get("numbering")) == (True, True)
    r2 = client_v2.post("/api/p/alpha/layouts", json=body, headers=auth("alice"))
    assert r2.status_code == 201 and r2.json()["name"] == "Carried structure (2)"


# ── R-V1.4 references are stripped; "Choose a value"; Generate refused ───────

def test_r_v1_4_references_are_reset_and_generate_is_refused(client_v2, auth):
    doc = preset_file([{"block_type": "dashboard_chart", "options": {"chart_id": 33}},
                       {"block_type": "test_results", "options": {"evaluations": [IDS["EVAL_A_V2"]]}}])
    r = create(client_v2, auth, preset_file=doc)
    assert r.status_code == 201, r.text[:300]
    lay = r.json()
    chart, tests = lay["blocks"]
    assert "chart_id" not in chart["options"]
    assert tests["options"].get("evaluations", "all") == "all"
    problems = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/validate", headers=auth("alice")).json()["problems"]
    assert {"instance_id": chart["instance_id"], "pointer": "/chart_id", "message": "Choose a value"}.items() <= \
        next(p for p in problems if p["pointer"] == "/chart_id").items()
    g = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert g.status_code == 422 and error_code(g) == "invalid_options"


# ── R-V1.5 unknown block types ───────────────────────────────────────────────

def test_r_v1_5_unknown_block_types_are_all_listed(client_v2, auth):
    doc = preset_file([{"block_type": "cover", "options": {}}, {"block_type": "ghost", "options": {}},
                       {"block_type": "phantom", "options": {}}])
    r = create(client_v2, auth, preset_file=doc)
    assert r.status_code == 422 and error_code(r) == "unknown_block_type"
    assert {"ghost", "phantom"} <= set(json.dumps(r.json()["error"]["details"]).replace('"', " ").split())


# ── R-V1.6 duplicate ─────────────────────────────────────────────────────────

def test_r_v1_6_duplicate_names_copy_then_copy_2(client_v2, auth):
    lay = create(client_v2, auth, name="Board pack", blocks=[v2blk("cover"), v2blk("free_text", text="x")]).json()
    one = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={}, headers=auth("alice"))
    assert one.status_code == 201, "missing feature: POST .../duplicate"
    two = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={}, headers=auth("alice"))
    assert one.json()["name"] == "Board pack (copy)" and two.json()["name"] == "Board pack (copy 2)"
    named = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={"name": "Mine"}, headers=auth("alice"))
    assert named.status_code == 201 and named.json()["name"] == "Mine"


def test_r_v1_6_a_copy_keeps_everything_but_ids_revision_and_reports(client_v2, auth):
    lay = create(client_v2, auth, name="Original", show_index=False, numbering=True,
                 blocks=[v2blk("cover"), v2blk("chapter", title="C"), v2blk("ai_card")]).json()
    body = {**{k: lay[k] for k in ("name", "template_id", "revision", "blocks")},
            "coverage": [{"objective_id": "R1.1", "tests": ["LangBiTe"], "checklists": ["cl-1"]}]}
    saved = client_v2.put(f"/api/p/alpha/layouts/{lay['id']}", json=body, headers=auth("alice"))
    assert saved.status_code == 200, saved.text[:300]
    client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={}, headers=auth("alice"))
    assert r.status_code == 201
    copy_ = r.json()
    src = saved.json()
    assert copy_["id"] != src["id"] and copy_["revision"] == 1
    for key in ("template_id", "show_index", "numbering", "coverage"):
        assert copy_[key] == src[key], key
    assert "language" not in copy_                                       # R2-D1.13: no language copied
    assert [b["options"] for b in copy_["blocks"]] == [b["options"] for b in src["blocks"]]
    assert not {b["instance_id"] for b in copy_["blocks"]} & {b["instance_id"] for b in src["blocks"]}
    assert client_v2.get(f"/api/p/alpha/layouts/{copy_['id']}/reports", headers=auth("alice")).json() == []


def test_r_v1_6_a_viewer_cannot_duplicate(client_v2, auth):
    lay = create(client_v2, auth).json()
    assert client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={},
                          headers=auth("victor")).status_code == 403


# ── R-V1.7, R-V1.9 export as a preset file ───────────────────────────────────

def _texty_layout(client, auth):
    blocks = [v2blk("cover", report_title="Kept title", subtitle="Kept subtitle"),
              v2blk("free_text", text="Secret findings", commentary="An aside"),
              v2blk("test_results", evaluations=[IDS["EVAL_A_V2"]], commentary="About the tests"),
              v2blk("dashboard_chart", chart_id=33)]
    return create(client, auth, name="Board Pack: Q3", blocks=blocks).json()


def test_r_v1_7_export_is_a_preset_file(client_v2, auth):
    lay = _texty_layout(client_v2, auth)
    r = client_v2.get(f"/api/p/alpha/layouts/{lay['id']}/export", headers=auth("victor"))
    assert r.status_code == 200, "missing feature: GET .../export"
    assert 'attachment; filename="report-preset-board-pack-q3.json"' in r.headers["content-disposition"]
    doc = r.json()
    assert set(doc) == {"format", "version", "name", "description", "show_index", "numbering", "blocks"}
    assert (doc["format"], doc["version"]) == ("aisc-report-preset", 2)
    assert [set(b) for b in doc["blocks"]] == [{"block_type", "options"}] * 4
    tests, chart = doc["blocks"][2]["options"], doc["blocks"][3]["options"]
    assert tests.get("evaluations", "all") == "all" and "chart_id" not in chart


def test_r_v1_9_texts_become_placeholders_unless_kept(client_v2, auth):
    lay = _texty_layout(client_v2, auth)
    r = client_v2.get(f"/api/p/alpha/layouts/{lay['id']}/export", headers=auth("alice"))
    assert r.status_code == 200, "missing feature: GET .../export"
    doc = r.json()
    cover, free, tests = (b["options"] for b in doc["blocks"][:3])
    assert (cover["report_title"], cover["subtitle"]) == ("Kept title", "Kept subtitle")
    assert free["text"] == "Write this section." and free.get("commentary", "") == ""
    assert tests.get("commentary", "") == ""
    kept = client_v2.get(f"/api/p/alpha/layouts/{lay['id']}/export?keep_text=true", headers=auth("alice")).json()
    assert kept["blocks"][1]["options"]["text"] == "Secret findings"
    assert kept["blocks"][1]["options"]["commentary"] == "An aside"


# ── R-V1.8, R-V1.11 saved presets ────────────────────────────────────────────

def test_r_v1_8_import_a_file_and_the_name_gets_a_suffix(client_v2, auth):
    doc = preset_file([{"block_type": "cover", "options": {}}], name="Imported look")
    r1 = client_v2.post("/api/p/alpha/layouts", json={"file": doc}, headers=auth("alice"))
    assert r1.status_code == 201, r1.text[:300]
    r2 = client_v2.post("/api/p/alpha/layouts", json={"file": doc}, headers=auth("alice"))
    assert (r1.json()["name"], r2.json()["name"]) == ("Imported look", "Imported look (2)")


# ── R-V1.10 import checks ────────────────────────────────────────────────────

@pytest.mark.parametrize("doc", [
    {"format": "aisc-report-template", "version": 1, "name": "x", "blocks": []},
    {"format": "aisc-report-preset", "version": 3, "name": "x", "blocks": []},
    ["not", "an", "object"],
])
def test_r_v1_10_not_a_preset(client_v2, auth, doc):
    r = client_v2.post("/api/p/alpha/layouts", json={"file": doc}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "not_a_preset"


def test_r_v1_10_at_most_50_blocks(client_v2, auth):
    doc = preset_file([{"block_type": "free_text", "options": {"text": "x"}}] * 51)
    r = client_v2.post("/api/p/alpha/layouts", json={"file": doc}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) is not None


def test_r_v1_10_invalid_options_name_the_block_index(client_v2, auth):
    doc = preset_file([{"block_type": "cover", "options": {}},
                       {"block_type": "dashboard_chart", "options": {"width": 5}}])
    r = client_v2.post("/api/p/alpha/layouts", json={"file": doc}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "invalid_options"
    assert any("/blocks/1" in (d.get("pointer") or "") for d in r.json()["error"]["details"])


def test_r_v1_10_unknown_block_type_on_import(client_v2, auth):
    r = client_v2.post("/api/p/alpha/layouts", json={"file": preset_file([{"block_type": "ghost", "options": {}}])},
                       headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "unknown_block_type"


def test_r_v1_10_a_preset_with_two_covers_is_refused(client_v2, auth):
    r = create(client_v2, auth, preset_file=preset_file([{"block_type": "cover", "options": {}}] * 2))
    assert r.status_code == 422 and error_code(r) == "duplicate_cover"


# ── R-V1.12 no link to the preset ────────────────────────────────────────────

# ── 2.5 edge cases ───────────────────────────────────────────────────────────

def test_r_v1_edge_zero_block_preset_starts_empty_and_is_not_generated(client_v2, auth):
    lay = create(client_v2, auth, preset_file=preset_file([])).json()
    assert lay["blocks"] == [] and lay.get("show_index") is True
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "empty_layout"


def test_r_v1_edge_a_language_no_longer_offered_falls_back_to_english_with_a_notice(client_v2, auth):
    """Changed by R2-D1.13 (D1): any language in a preset file is ignored, with no notice."""
    r = create(client_v2, auth, preset_file=preset_file([{"block_type": "cover", "options": {}}], language="de"))
    assert r.status_code == 201, r.text[:300]
    assert "language" not in r.json()
    assert "language" not in json.dumps(r.json().get("details") or []) and \
        "language" not in json.dumps(r.json().get("notices") or [])


# ── fix round 1, finding 4: every free text is dropped unless "Keep texts" ────

def _chapter_layout(client, auth):
    blocks = [v2blk("cover", report_title="Kept title"),
              v2blk("chapter", title="Findings", intro="Findings for Bank X show a gap.", commentary="Chapter aside"),
              v2blk("free_text", text="Secret findings")]
    return create(client, auth, name=unique("Chapters"), blocks=blocks).json()


def test_fix4_the_layout_export_drops_the_intro_and_keep_text_keeps_it(client_v2, auth):
    lay = _chapter_layout(client_v2, auth)
    doc = client_v2.get(f"/api/p/alpha/layouts/{lay['id']}/export", headers=auth("alice")).json()
    assert doc["blocks"][1]["options"].get("intro", "") == ""
    kept = client_v2.get(f"/api/p/alpha/layouts/{lay['id']}/export?keep_text=true", headers=auth("alice")).json()
    assert kept["blocks"][1]["options"]["intro"] == "Findings for Bank X show a gap."


def test_fix4_any_long_text_option_of_a_plugin_block_is_dropped_too():
    """The rule follows the block type's schema: every text option longer than a title is free text."""
    from report_composer import presets

    plugin_type = {"type_id": "auditor_notes", "default_options": {"notes": "", "heading": "Notes"},
                   "options_schema": {"type": "object", "properties": {
                       "heading": {"type": "string", "maxLength": 200},
                       "notes": {"type": "string", "maxLength": 4000},
                       "summary": {"type": "string", "minLength": 1, "maxLength": 2000}}}}
    layout = {"name": "L", "blocks": [{"block_type": "auditor_notes",
                                       "options": {"heading": "Auditor", "notes": "Client X", "summary": "Y"}}]}
    p = presets.from_layout(layout, [plugin_type])
    options = p.blocks[0]["options"]
    assert options["heading"] == "Auditor"
    assert options["notes"] == ""
    assert options["summary"] == presets.PLACEHOLDER             # a required text keeps a valid value
    kept = presets.from_layout(layout, [plugin_type], keep_text=True).blocks[0]["options"]
    assert kept == {"heading": "Auditor", "notes": "Client X", "summary": "Y"}
