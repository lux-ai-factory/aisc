"""All reports are in English.

The composer has no language choice: no Language control, no call to GET /v1/languages, a
`language` key sent by an older client is accepted and ignored, nothing is written to or read from the
`language` columns, and no snapshot carries a language. Rows and files that still hold "fr" load and render
(in English). Database tests on the composer bed with the v2 fake renderer.
"""
import json
from pathlib import Path

import pytest

from conftest import IDS, new_layout, pdb_of, some_template
from v2_fakes import client_v2, fake_v2, scalar_json, unique, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]
APP = Path(__file__).resolve().parents[1] / "report_composer"


def soup(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


def lay(client, auth, **body):
    body.setdefault("name", unique("English"))
    body.setdefault("blocks", [v2blk("cover"), v2blk("ai_card")])
    return new_layout(client, auth, **body)


def put(client, auth, layout, **changes):
    body = {k: layout[k] for k in ("name", "template_id", "revision", "blocks")}
    body.update(changes)
    return client.put(f"/api/p/alpha/layouts/{layout['id']}", json=body, headers=auth("alice"))


# no Language control, no languages call

def test_the_editor_has_no_language_control(client_v2, auth):
    lay_ = lay(client_v2, auth)
    doc = soup(client_v2.get(f"/p/alpha/layouts/{lay_['id']}", headers=auth("alice")).text)
    assert doc.find("select", attrs={"data-control": "language"}) is None
    assert doc.find(attrs={"data-control": "language"}) is None


# a language key is accepted and ignored

def test_post_accepts_and_ignores_a_language(client_v2, auth):
    body = {"name": unique("Posted"), "system_id": IDS["A_V2"], "template_id": some_template(client_v2, auth),
            "blocks": [v2blk("cover")], "language": "xx"}
    r = client_v2.post("/api/p/alpha/layouts", json=body, headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert "language" not in r.json()


def test_put_accepts_and_ignores_a_language(client_v2, auth):
    lay_ = lay(client_v2, auth)
    r = put(client_v2, auth, lay_, language="xx")
    assert r.status_code == 200, r.text[:300]
    assert "language" not in r.json()


def test_draft_preview_accepts_and_ignores_a_language(client_v2, auth, fake_v2):
    lay_ = lay(client_v2, auth)
    body = {"template_id": lay_["template_id"], "language": "de", "blocks": lay_["blocks"]}
    r = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/preview", json=body, headers=auth("alice"))
    assert r.status_code == 200, r.text[:300]
    assert "language" not in fake_v2.snapshots[-1]


def test_the_layout_views_carry_no_language(client_v2, auth):
    lay_ = lay(client_v2, auth)
    one = client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}", headers=auth("victor")).json()
    rows = client_v2.get("/api/p/alpha/layouts", headers=auth("victor")).json()
    dup = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/duplicate", json={}, headers=auth("alice"))
    assert dup.status_code == 201, dup.text[:300]
    assert "language" not in lay_ and "language" not in one
    assert rows and all("language" not in r for r in rows)
    assert "language" not in dup.json()


# no snapshot carries a language

def test_preview_and_generate_snapshots_carry_no_language(client_v2, auth, fake_v2, bed):
    lay_ = lay(client_v2, auth)
    client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}/preview", headers=auth("victor"))
    assert "language" not in fake_v2.snapshots[-1]
    for fmt in ("pdf", "docx"):
        g = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/reports", json={"format": fmt, "system_id": IDS["A_V2"]},
                           headers=auth("alice"))
        assert g.status_code == 201, g.text[:300]
        assert "language" not in fake_v2.snapshots[-1], fmt
        stored = scalar_json(bed, "SELECT snapshot::text FROM report_composer.generated_report"
                                  f" WHERE id = '{g.json()['id']}'", db=pdb_of("A"))
        assert "language" not in stored, fmt


# presets carry no language

@pytest.mark.parametrize("preset_id", ["summary", "management-overview", "assessment-report", "eu-ai-act",
                                       "technical-dossier"])
def test_built_in_preset_files_have_no_language(preset_id):
    doc = json.loads((APP / "presets" / f"{preset_id}.json").read_text(encoding="utf-8"))
    assert "language" not in doc


def test_exports_write_no_language(client_v2, auth):
    lay_ = lay(client_v2, auth)
    doc = client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}/export", headers=auth("alice")).json()
    assert set(doc) == {"format", "version", "name", "description", "show_index", "numbering", "blocks"}
    assert doc["version"] == 2


def test_import_with_any_language_is_accepted_and_ignored(client_v2, auth):
    doc = {"format": "aisc-report-preset", "version": 1, "name": unique("Imported"), "description": "",
           "language": "xx", "toc": "on", "numbering": True, "blocks": [{"block_type": "cover", "options": {}}]}
    made = client_v2.post("/api/p/alpha/layouts", json={"file": doc, "name": unique("From file"),
                                                       "template_id": some_template(client_v2, auth)},
                          headers=auth("alice"))
    assert made.status_code == 201, made.text[:300]
    assert "language" not in json.dumps(made.json())             # no language key, no language notice
    exported = client_v2.get(f"/api/p/alpha/layouts/{made.json()['id']}/export", headers=auth("alice")).json()
    assert "language" not in exported and (exported["show_index"], exported["numbering"]) == (True, True)
