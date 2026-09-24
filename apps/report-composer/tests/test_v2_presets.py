"""V1: reusable report structures (report run v2, 01-specs.md section 2: R-V1.1 to R-V1.12).

Presets: four built-in JSON files, saved presets (table report_composer.preset, platform wide) and
preset files. Database tests on the composer bed, with the v2 fake renderer (v2_fakes.py).
"""
import json
from pathlib import Path

import pytest

from conftest import DEFAULT_ORDER, IDS, error_code, new_layout, some_template
from v2_fakes import clean_presets, client_v2, fake_v2, unique, scalar_json, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts", "clean_presets")]

PRESETS_DIR = Path(__file__).resolve().parents[1] / "report_composer/presets"
BUILT_IN = ["full-assessment", "eu-ai-act", "internal-audit", "executive-summary"]
SEQUENCES = {
    "full-assessment": DEFAULT_ORDER,
    "eu-ai-act": ["cover", "key_figures", "chapter", "ai_card", "risk_classification", "chapter",
                  "control_objectives", "summary_coverage", "chapter", "test_results", "control_answers",
                  "appendix", "free_text"],
    "internal-audit": ["cover", "free_text", "key_figures", "control_answers", "test_results", "summary_coverage",
                       "free_text"],
    "executive-summary": ["cover", "key_figures", "chart", "summary_coverage", "changes_since"],
}


def preset_file(blocks, name="Carried structure", **over):
    doc = {"format": "aisc-report-preset", "version": 1, "name": name, "description": "", "language": "en",
           "toc": "auto", "numbering": False, "blocks": blocks}
    doc.update(over)
    return doc


def create(client, auth, who="alice", slug="alpha", **body):
    body.setdefault("name", unique("Layout"))
    body.setdefault("system_id", IDS["A_V2"])
    if "template_id" not in body:
        body["template_id"] = some_template(client, auth, slug=slug, who=who)
    return client.post(f"/api/p/{slug}/layouts", json=body, headers=auth(who))


def save_preset(client, auth, layout_id, who="alice", **body):
    r = client.post(f"/api/p/alpha/layouts/{layout_id}/preset", json=body, headers=auth(who))
    assert r.status_code == 201, "missing feature: POST /api/p/{ref}/layouts/{id}/preset"
    return r.json()["id"]


def _load(name):
    path = PRESETS_DIR / f"{name}.json"
    if not path.exists():
        pytest.fail(f"missing feature: built-in preset file report_composer/presets/{name}.json", pytrace=False)
    return json.loads(path.read_text())


# ── R-V1.1 built-in presets ──────────────────────────────────────────────────

@pytest.mark.parametrize("preset_id", BUILT_IN)
def test_r_v1_1_built_in_preset_files_hold_the_block_sequence(preset_id):
    doc = _load(preset_id)
    assert [b["block_type"] for b in doc["blocks"]] == SEQUENCES[preset_id]
    assert all(set(b) == {"block_type", "options"} for b in doc["blocks"])


def test_r_v1_1_built_in_preset_document_settings():
    full, eu, audit, ex = (_load(p) for p in BUILT_IN)
    assert (full.get("toc"), full.get("numbering"), full.get("language")) == ("auto", False, "en")
    assert (eu.get("toc"), eu.get("numbering")) == ("on", True)
    assert (audit.get("toc"), audit.get("numbering")) == ("on", True)
    assert ex.get("toc") == "off"
    eu_co = next(b for b in eu["blocks"] if b["block_type"] == "control_objectives")
    assert eu_co["options"].get("show_severity") is True
    chapters = [b["options"].get("title") for b in eu["blocks"] if b["block_type"] == "chapter"]
    assert chapters == ["System and risks", "Control objectives", "Evidence"]
    assert next(b for b in eu["blocks"] if b["block_type"] == "free_text")["options"].get("title") == "Method"
    assert [b["options"].get("title") for b in audit["blocks"] if b["block_type"] == "free_text"] == ["Scope", "Findings"]
    assert next(b for b in audit["blocks"] if b["block_type"] == "summary_coverage")["options"].get("show_uncovered_only") is True
    assert next(b for b in ex["blocks"] if b["block_type"] == "chart")["options"].get("dataset") == "coverage_status"
    assert next(b for b in ex["blocks"] if b["block_type"] == "summary_coverage")["options"].get("show_uncovered_only") is True


def test_r_v1_1_the_list_starts_with_the_four_built_ins_in_order(client_v2, auth):
    r = client_v2.get("/api/presets", headers=auth("victor"))
    assert r.status_code == 200, "missing feature: GET /api/presets"
    rows = r.json()
    assert [p["id"] for p in rows[:4]] == BUILT_IN
    assert [p["name"] for p in rows[:4]] == ["Full assessment", "EU AI Act conformity", "Internal audit",
                                             "Executive summary"]
    assert all(p["built_in"] is True for p in rows[:4])
    assert rows[1]["block_types"] == SEQUENCES["eu-ai-act"]
    assert set(rows[0]) >= {"id", "name", "description", "built_in", "block_types"}


# ── R-V1.2, R-V1.3 creating a layout from a preset ───────────────────────────

def test_r_v1_2_no_preset_and_no_blocks_is_the_full_assessment(client_v2, auth):
    r = create(client_v2, auth)
    assert r.status_code == 201, r.text[:300]
    lay = r.json()
    assert [b["block_type"] for b in lay["blocks"]] == DEFAULT_ORDER
    assert (lay.get("toc"), lay.get("numbering"), lay.get("language")) == ("auto", False, "en")


@pytest.mark.parametrize("preset_id", BUILT_IN)
def test_r_v1_3_a_layout_from_a_built_in_preset(client_v2, auth, preset_id):
    r = create(client_v2, auth, preset=preset_id)
    assert r.status_code == 201, r.text[:300]
    lay = r.json()
    assert [b["block_type"] for b in lay["blocks"]] == SEQUENCES[preset_id]
    doc = _load(preset_id)
    assert lay.get("toc") == doc.get("toc", "auto") and lay.get("numbering") == doc.get("numbering", False)


def test_r_v1_3_new_instance_ids_every_time(client_v2, auth):
    a = create(client_v2, auth, preset="internal-audit").json()
    b = create(client_v2, auth, preset="internal-audit").json()
    ids_a = {x["instance_id"] for x in a["blocks"]}
    ids_b = {x["instance_id"] for x in b["blocks"]}
    assert len(ids_a) == len(a["blocks"]) and not ids_a & ids_b
    assert [x["block_type"] for x in a["blocks"]] == SEQUENCES["internal-audit"]


def test_r_v1_3_empty_preset_gives_no_blocks(client_v2, auth):
    r = create(client_v2, auth, preset="empty")
    assert r.status_code == 201 and r.json()["blocks"] == []
    assert create(client_v2, auth, preset="empty").json().get("toc") == "auto"


def test_r_v1_3_unknown_preset(client_v2, auth):
    r = create(client_v2, auth, preset="no-such-preset")
    assert r.status_code == 422 and error_code(r) == "unknown_preset"
    r = create(client_v2, auth, preset="00000000-0000-4000-8000-00000000beef")
    assert r.status_code == 422 and error_code(r) == "unknown_preset"


@pytest.mark.parametrize("extra", [
    {"preset": "eu-ai-act", "blocks": []},
    {"preset": "eu-ai-act", "preset_file": {"format": "aisc-report-preset", "version": 1, "name": "x", "blocks": []}},
    {"preset_file": {"format": "aisc-report-preset", "version": 1, "name": "x", "blocks": []}, "blocks": []},
])
def test_r_v1_3_at_most_one_source_of_blocks(client_v2, auth, extra):
    r = create(client_v2, auth, **extra)
    assert r.status_code == 422 and error_code(r) == "invalid_request"


def test_r_v1_3_a_layout_from_a_preset_file_takes_its_name_from_the_file(client_v2, auth):
    doc = preset_file([{"block_type": "cover", "options": {"report_title": "Carried"}},
                       {"block_type": "free_text", "options": {"text": "x"}}], name="Carried structure",
                      toc="on", numbering=True)
    body = {"system_id": IDS["A_V2"], "template_id": some_template(client_v2, auth), "preset_file": doc}
    r = client_v2.post("/api/p/alpha/layouts", json=body, headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert r.json()["name"] == "Carried structure"
    assert (r.json().get("toc"), r.json().get("numbering")) == ("on", True)
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
    g = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
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
    lay = create(client_v2, auth, name="Board pack", preset="internal-audit").json()
    one = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={}, headers=auth("alice"))
    assert one.status_code == 201, "missing feature: POST .../duplicate"
    two = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={}, headers=auth("alice"))
    assert one.json()["name"] == "Board pack (copy)" and two.json()["name"] == "Board pack (copy 2)"
    named = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={"name": "Mine"}, headers=auth("alice"))
    assert named.status_code == 201 and named.json()["name"] == "Mine"


def test_r_v1_6_a_copy_keeps_everything_but_ids_revision_and_reports(client_v2, auth):
    lay = create(client_v2, auth, name="Original", preset="eu-ai-act").json()
    body = {**{k: lay[k] for k in ("name", "system_id", "template_id", "revision", "blocks")}, "language": "fr",
            "coverage": [{"objective_id": "R1.1", "tests": ["LangBiTe"], "checklists": ["cl-1"]}]}
    saved = client_v2.put(f"/api/p/alpha/layouts/{lay['id']}", json=body, headers=auth("alice"))
    assert saved.status_code == 200, saved.text[:300]
    client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={}, headers=auth("alice"))
    assert r.status_code == 201
    copy_ = r.json()
    src = saved.json()
    assert copy_["id"] != src["id"] and copy_["revision"] == 1
    for key in ("system_id", "template_id", "language", "toc", "numbering", "coverage"):
        assert copy_[key] == src[key], key
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
    assert set(doc) == {"format", "version", "name", "description", "language", "toc", "numbering", "blocks"}
    assert (doc["format"], doc["version"]) == ("aisc-report-preset", 1)
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

def test_r_v1_8_save_list_export_a_saved_preset(client_v2, auth, bed):
    lay = _texty_layout(client_v2, auth)
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/preset", json={"name": "Bank audit", "description": "d"},
                       headers=auth("alice"))
    assert r.status_code == 201, "missing feature: POST .../preset"
    pid = r.json()["id"]
    rows = client_v2.get("/api/presets", headers=auth("bob")).json()   # every signed-in user sees it
    saved = [p for p in rows if p["id"] == pid]
    assert saved and saved[0]["built_in"] is False and rows.index(saved[0]) >= 4
    assert saved[0]["block_types"] == ["cover", "free_text", "test_results", "dashboard_chart"]
    exported = client_v2.get(f"/api/presets/{pid}/export", headers=auth("bob"))
    assert exported.status_code == 200 and exported.json()["format"] == "aisc-report-preset"
    assert exported.json()["blocks"][1]["options"]["text"] == "Write this section."
    source = bed.scalar("platform", f"SELECT source_project_id::text FROM report_composer.preset WHERE id = '{pid}'")
    assert source == IDS["A"]


def test_r_v1_8_keep_text_on_a_saved_preset(client_v2, auth):
    lay = _texty_layout(client_v2, auth)
    pid = save_preset(client_v2, auth, lay["id"], name="Kept", keep_text=True)
    doc = client_v2.get(f"/api/presets/{pid}/export", headers=auth("alice")).json()
    assert doc["blocks"][1]["options"]["text"] == "Secret findings"


def test_r_v1_8_a_viewer_cannot_save_a_preset(client_v2, auth):
    lay = create(client_v2, auth).json()
    assert client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/preset", json={"name": "No"},
                          headers=auth("victor")).status_code == 403


def test_r_v1_8_delete_by_creator_or_admin_only(client_v2, auth):
    lay = create(client_v2, auth).json()
    mk = lambda n: save_preset(client_v2, auth, lay["id"], name=n)  # noqa: E731
    a, b = mk("Alice one"), mk("Alice two")
    assert client_v2.delete(f"/api/presets/{a}", headers=auth("bob")).status_code == 403
    assert client_v2.delete(f"/api/presets/{a}", headers=auth("alice")).status_code == 204
    assert client_v2.delete(f"/api/presets/{b}", headers=auth("olga", roles=("primary-user", "admin"))).status_code == 204
    assert all(p["id"] not in (a, b) for p in client_v2.get("/api/presets", headers=auth("alice")).json())


def test_r_v1_8_built_in_presets_cannot_be_deleted(client_v2, auth):
    r = client_v2.delete("/api/presets/eu-ai-act", headers=auth("olga", roles=("primary-user", "admin")))
    assert r.status_code == 403


def test_r_v1_8_import_a_preset_file_and_the_name_gets_a_suffix(client_v2, auth):
    doc = preset_file([{"block_type": "cover", "options": {}}], name="Imported look")
    r1 = client_v2.post("/api/presets/import", json=doc, headers=auth("bob"))
    assert r1.status_code == 201, "missing feature: POST /api/presets/import"
    r2 = client_v2.post("/api/presets/import", json=doc, headers=auth("bob"))
    assert (r1.json()["name"], r2.json()["name"]) == ("Imported look", "Imported look (2)")


def test_r_v1_8_a_saved_preset_is_a_starting_point(client_v2, auth):
    lay = create(client_v2, auth, preset="executive-summary").json()
    pid = save_preset(client_v2, auth, lay["id"], name="Exec")
    r = create(client_v2, auth, slug="gamma", preset=pid, system_id=IDS["C_V1"])
    assert r.status_code == 201, r.text[:300]
    assert [b["block_type"] for b in r.json()["blocks"]] == SEQUENCES["executive-summary"]


@pytest.mark.parametrize("name", ["", "x" * 121])
def test_r_v1_11_preset_names_are_1_to_120_characters(client_v2, auth, name):
    lay = create(client_v2, auth).json()
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/preset", json={"name": name}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "invalid_request"


def test_r_v1_11_preset_names_are_unique_platform_wide(client_v2, auth):
    a = create(client_v2, auth).json()
    g = create(client_v2, auth, slug="gamma", system_id=IDS["C_V1"]).json()
    assert client_v2.post(f"/api/p/alpha/layouts/{a['id']}/preset", json={"name": "Shared"},
                          headers=auth("alice")).status_code == 201
    r = client_v2.post(f"/api/p/gamma/layouts/{g['id']}/preset", json={"name": "Shared"}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "name_taken"


# ── R-V1.10 import checks ────────────────────────────────────────────────────

@pytest.mark.parametrize("doc", [
    {"format": "aisc-report-template", "version": 1, "name": "x", "blocks": []},
    {"format": "aisc-report-preset", "version": 2, "name": "x", "blocks": []},
    ["not", "an", "object"],
])
def test_r_v1_10_not_a_preset(client_v2, auth, doc):
    r = client_v2.post("/api/presets/import", json=doc, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "not_a_preset"


def test_r_v1_10_at_most_50_blocks(client_v2, auth):
    doc = preset_file([{"block_type": "free_text", "options": {"text": "x"}}] * 51)
    r = client_v2.post("/api/presets/import", json=doc, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) is not None


def test_r_v1_10_invalid_options_name_the_block_index(client_v2, auth):
    doc = preset_file([{"block_type": "cover", "options": {}},
                       {"block_type": "dashboard_chart", "options": {"width": 5}}])
    r = client_v2.post("/api/presets/import", json=doc, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "invalid_options"
    assert any("/blocks/1" in (d.get("pointer") or "") for d in r.json()["error"]["details"])


def test_r_v1_10_unknown_block_type_on_import(client_v2, auth):
    r = client_v2.post("/api/presets/import", json=preset_file([{"block_type": "ghost", "options": {}}]),
                       headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "unknown_block_type"


def test_r_v1_10_a_preset_with_two_covers_is_refused(client_v2, auth):
    r = create(client_v2, auth, preset_file=preset_file([{"block_type": "cover", "options": {}}] * 2))
    assert r.status_code == 422 and error_code(r) == "duplicate_cover"


# ── R-V1.12 no link to the preset ────────────────────────────────────────────

def test_r_v1_12_deleting_a_preset_does_not_change_the_layout(client_v2, auth):
    src = create(client_v2, auth, preset="internal-audit").json()
    pid = save_preset(client_v2, auth, src["id"], name="Gone soon")
    made = create(client_v2, auth, preset=pid).json()
    assert client_v2.delete(f"/api/presets/{pid}", headers=auth("alice")).status_code == 204
    again = client_v2.get(f"/api/p/alpha/layouts/{made['id']}", headers=auth("alice")).json()
    assert again["blocks"] == made["blocks"] and again["revision"] == made["revision"]
    assert "preset" not in again and "preset_id" not in again


# ── 2.5 edge cases ───────────────────────────────────────────────────────────

def test_r_v1_edge_zero_block_preset_starts_empty_and_is_not_generated(client_v2, auth):
    lay = create(client_v2, auth, preset_file=preset_file([])).json()
    assert lay["blocks"] == [] and lay.get("toc") == "auto"
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "empty_layout"


def test_r_v1_edge_a_language_no_longer_offered_falls_back_to_english_with_a_notice(client_v2, auth):
    r = create(client_v2, auth, preset_file=preset_file([{"block_type": "cover", "options": {}}], language="de"))
    assert r.status_code == 201, r.text[:300]
    assert r.json().get("language") == "en"
    assert "de" in json.dumps(r.json().get("details"))
