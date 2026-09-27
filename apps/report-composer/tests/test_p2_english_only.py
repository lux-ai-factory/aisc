"""Part 2, D1: all reports in English (10-specs-part2.md R2-D1.9 to R2-D1.13, R2-C.1).

The composer has no language choice any more: no Language control, no call to GET /v1/languages, a
`language` key sent by an older client is accepted and ignored, nothing is written to or read from the
`language` columns, and no snapshot carries a language. Rows and files that still hold "fr" load and render
(in English). Database tests on the composer bed with the v2 fake renderer.
"""
import json
from pathlib import Path

import pytest

from conftest import IDS, error_code, new_layout, pdb_of, some_template
from v2_fakes import clean_presets, client_v2, fake_v2, scalar_json, unique, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts", "clean_presets")]
APP = Path(__file__).resolve().parents[1] / "report_composer"


def soup(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


def lay(client, auth, **body):
    body.setdefault("name", unique("English"))
    body.setdefault("system_id", IDS["A_V2"])
    body.setdefault("blocks", [v2blk("cover"), v2blk("ai_card")])
    return new_layout(client, auth, **body)


def put(client, auth, layout, **changes):
    body = {k: layout[k] for k in ("name", "system_id", "template_id", "revision", "blocks")}
    body.update(changes)
    return client.put(f"/api/p/alpha/layouts/{layout['id']}", json=body, headers=auth("alice"))


def row_language(bed, layout_id):
    return bed.scalar(pdb_of("A"), f"SELECT language FROM report_composer.layout WHERE id = '{layout_id}'")


# ── R2-D1.9 no Language control, no languages call ──────────────────────────

def test_r2_d1_9_the_editor_has_no_language_control(client_v2, auth):
    lay_ = lay(client_v2, auth)
    doc = soup(client_v2.get(f"/p/alpha/layouts/{lay_['id']}", headers=auth("alice")).text)
    assert doc.find("select", attrs={"data-control": "language"}) is None
    assert doc.find(attrs={"data-control": "language"}) is None


def test_r2_d1_9_composer_js_neither_reads_nor_sends_a_language():
    js = (APP / "static/composer.js").read_text(encoding="utf-8")
    assert "language" not in js


def test_r2_d1_9_the_composer_no_longer_calls_get_v1_languages():
    from report_composer import renderer_calls, renderer_client

    assert not hasattr(renderer_calls, "languages")
    assert not hasattr(renderer_client.HttpRendererClient, "languages")


# ── R2-D1.10 a language key is accepted and ignored ─────────────────────────

@pytest.mark.parametrize("value", ["fr", "de", "xx", "en"])
def test_r2_d1_10_post_accepts_and_ignores_a_language(client_v2, auth, value):
    body = {"name": unique("Posted"), "system_id": IDS["A_V2"], "template_id": some_template(client_v2, auth),
            "blocks": [v2blk("cover")], "language": value}
    r = client_v2.post("/api/p/alpha/layouts", json=body, headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert "language" not in r.json()


@pytest.mark.parametrize("value", ["fr", "de", "xx"])
def test_r2_d1_10_put_accepts_and_ignores_a_language(client_v2, auth, value):
    lay_ = lay(client_v2, auth)
    r = put(client_v2, auth, lay_, language=value)
    assert r.status_code == 200, r.text[:300]
    assert "language" not in r.json()


def test_r2_d1_10_draft_preview_accepts_and_ignores_a_language(client_v2, auth, fake_v2):
    lay_ = lay(client_v2, auth)
    body = {"system_id": lay_["system_id"], "template_id": lay_["template_id"], "language": "de",
            "blocks": lay_["blocks"]}
    r = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/preview", json=body, headers=auth("alice"))
    assert r.status_code == 200, r.text[:300]
    assert "language" not in fake_v2.snapshots[-1]


def test_r2_d1_10_the_layout_views_carry_no_language(client_v2, auth):
    lay_ = lay(client_v2, auth)
    one = client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}", headers=auth("victor")).json()
    rows = client_v2.get("/api/p/alpha/layouts", headers=auth("victor")).json()
    dup = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/duplicate", json={}, headers=auth("alice"))
    assert dup.status_code == 201, dup.text[:300]
    assert "language" not in lay_ and "language" not in one
    assert rows and all("language" not in r for r in rows)
    assert "language" not in dup.json()


def test_r2_d1_10_unknown_language_is_never_an_error(client_v2, auth):
    lay_ = lay(client_v2, auth)
    r = put(client_v2, auth, lay_, language="zz")
    assert error_code(r) != "unknown_language" and r.status_code == 200, r.text[:300]


# ── R2-D1.11 the language columns are neither written nor read ──────────────

def test_r2_d1_11_db_default_settings_have_no_language():
    from report_composer import db

    assert "language" not in db.DEFAULT_SETTINGS


def test_r2_d1_11_a_new_row_gets_the_column_default(client_v2, auth, bed):
    body = {"name": unique("Default"), "system_id": IDS["A_V2"], "template_id": some_template(client_v2, auth),
            "blocks": [v2blk("cover")], "language": "de"}
    r = client_v2.post("/api/p/alpha/layouts", json=body, headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert row_language(bed, r.json()["id"]) == "en"


def test_r2_d1_11_an_update_never_writes_the_language(client_v2, auth, bed):
    lay_ = lay(client_v2, auth)
    bed.psql(pdb_of("A"), f"UPDATE report_composer.layout SET language = 'fr' WHERE id = '{lay_['id']}'")
    r = put(client_v2, auth, lay_, language="en")
    assert r.status_code == 200, r.text[:300]
    assert row_language(bed, lay_["id"]) == "fr"                  # untouched, and without effect
    assert "language" not in r.json()


def test_r2_d1_11_a_saved_preset_stores_no_language(client_v2, auth, bed):
    lay_ = lay(client_v2, auth)
    r = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/preset", json={"name": unique("Saved")},
                       headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    stored = bed.scalar("platform", f"SELECT coalesce(language, 'NULL') FROM report_library.preset WHERE id = '{r.json()['id']}'")
    assert stored == "NULL"


# ── R2-D1.12 no snapshot carries a language ─────────────────────────────────

def test_r2_d1_12_preview_and_generate_snapshots_carry_no_language(client_v2, auth, fake_v2, bed):
    lay_ = lay(client_v2, auth)
    client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}/preview", headers=auth("victor"))
    assert "language" not in fake_v2.snapshots[-1]
    for fmt in ("pdf", "docx"):
        g = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/reports", json={"format": fmt}, headers=auth("alice"))
        assert g.status_code == 201, g.text[:300]
        assert "language" not in fake_v2.snapshots[-1], fmt
        stored = scalar_json(bed, "SELECT snapshot::text FROM report_composer.generated_report"
                                  f" WHERE id = '{g.json()['id']}'", db=pdb_of("A"))
        assert "language" not in stored, fmt


# ── R2-D1.13 presets carry no language ──────────────────────────────────────

@pytest.mark.parametrize("preset_id", ["full-assessment", "eu-ai-act", "internal-audit", "executive-summary"])
def test_r2_d1_13_built_in_preset_files_have_no_language(preset_id):
    doc = json.loads((APP / "presets" / f"{preset_id}.json").read_text(encoding="utf-8"))
    assert "language" not in doc


def test_r2_d1_13_exports_write_no_language(client_v2, auth):
    lay_ = lay(client_v2, auth)
    doc = client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}/export", headers=auth("alice")).json()
    assert set(doc) == {"format", "version", "name", "description", "toc", "numbering", "blocks"}
    assert doc["version"] == 1
    pid = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/preset", json={"name": unique("Exp")},
                         headers=auth("alice")).json()["id"]
    saved = client_v2.get(f"/api/presets/{pid}/export", headers=auth("alice")).json()
    assert "language" not in saved
    built_in = client_v2.get("/api/presets/eu-ai-act/export", headers=auth("alice")).json()
    assert "language" not in built_in


@pytest.mark.parametrize("value", ["fr", "de", "xx"])
def test_r2_d1_13_import_with_any_language_is_accepted_and_ignored(client_v2, auth, value):
    doc = {"format": "aisc-report-preset", "version": 1, "name": unique("Imported"), "description": "",
           "language": value, "toc": "on", "numbering": True, "blocks": [{"block_type": "cover", "options": {}}]}
    r = client_v2.post("/api/presets/import", json=doc, headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert "language" not in json.dumps(r.json())
    exported = client_v2.get(f"/api/presets/{r.json()['id']}/export", headers=auth("alice")).json()
    assert "language" not in exported and (exported["toc"], exported["numbering"]) == ("on", True)
    made = client_v2.post("/api/p/alpha/layouts", json={"system_id": IDS["A_V2"], "preset_file": doc,
                                                       "name": unique("From file"),
                                                       "template_id": some_template(client_v2, auth)},
                          headers=auth("alice"))
    assert made.status_code == 201, made.text[:300]
    assert "language" not in json.dumps(made.json())             # no language key, no language notice


# ── R2-C.1 rows and files that still hold "fr" load and render in English ────

def test_r2_c_1_a_layout_row_holding_fr_previews_and_generates_without_a_language(client_v2, auth, fake_v2, bed):
    lay_ = lay(client_v2, auth)
    bed.psql(pdb_of("A"), f"UPDATE report_composer.layout SET language = 'fr' WHERE id = '{lay_['id']}'")
    got = client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}", headers=auth("alice"))
    assert got.status_code == 200 and "language" not in got.json()
    p = client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}/preview", headers=auth("alice"))
    assert p.status_code == 200
    assert "language" not in fake_v2.snapshots[-1]
    g = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/reports", json={}, headers=auth("alice"))
    assert g.status_code == 201, g.text[:300]
    assert "language" not in fake_v2.snapshots[-1]


def test_r2_c_1_a_saved_preset_row_holding_fr_makes_an_english_layout(client_v2, auth, bed):
    src = lay(client_v2, auth)
    pid = client_v2.post(f"/api/p/alpha/layouts/{src['id']}/preset", json={"name": unique("Old French")},
                         headers=auth("alice")).json()["id"]
    bed.psql("platform", f"UPDATE report_library.preset SET language = 'fr' WHERE id = '{pid}'")
    r = client_v2.post("/api/p/alpha/layouts", json={"name": unique("From fr"), "system_id": IDS["A_V2"],
                                                    "template_id": some_template(client_v2, auth), "preset": pid},
                       headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert "language" not in json.dumps(r.json())
    exported = client_v2.get(f"/api/presets/{pid}/export", headers=auth("alice")).json()
    assert "language" not in exported
