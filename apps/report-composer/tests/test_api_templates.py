"""Templates: a report's look, orthogonal to its layout (user decision, 2026-09-24).

A template is font, base font size, primary and accent colour, and a logo. It belongs to one
project; a project has any number. It can be exported as a file and imported into another
project. A layout (blocks and their order) is saved only with one of its project's templates,
and only what is saved is generated, in that template's look.
"""
import base64
import json

import pytest

from conftest import IDS, blk, error_code, new_layout, new_template, put_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32).decode("ascii")
LOGO = {"mime": "image/png", "data_base64": PNG}


# ── templates of a project ───────────────────────────────────────────────────

def test_an_editor_makes_a_template_and_the_project_lists_it(client, auth):
    t = new_template(client, auth, name="Bank X", font="liberation-serif", font_size_pt=11,
                     primary_color="#123456", accent_color="#abcdef", logo=LOGO)
    assert t["name"] == "Bank X" and t["has_logo"] is True
    listed = client.get("/api/p/alpha/templates", headers=auth("victor")).json()   # a viewer may list
    assert [x["name"] for x in listed] == ["Bank X"]
    assert listed[0] == {**listed[0], "font": "liberation-serif", "font_size_pt": 11,
                         "primary_color": "#123456", "accent_color": "#abcdef", "has_logo": True}
    assert "logo" not in listed[0]                                                 # the list carries no image


def test_a_template_belongs_to_its_project(client, auth):
    new_template(client, auth, name="Alpha look")
    assert client.get("/api/p/gamma/templates", headers=auth("alice")).json() == []


def test_two_templates_of_a_project_cannot_share_a_name(client, auth):
    new_template(client, auth, name="Same")
    r = client.post("/api/p/alpha/templates", json={"name": "Same", "font": "inter", "font_size_pt": 10,
                                                   "primary_color": "#000000", "accent_color": "#ffffff"},
                    headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "name_taken"


@pytest.mark.parametrize("over,code", [
    ({"font": "comic-sans"}, "invalid_template"),
    ({"font_size_pt": 30}, "invalid_template"),
    ({"primary_color": "blue"}, "invalid_template"),
    ({"accent_color": "#12345"}, "invalid_template"),
    ({"logo": {"mime": "application/pdf", "data_base64": PNG}}, "invalid_template"),
    ({"logo": {"mime": "image/png", "data_base64": "not base64!"}}, "invalid_template"),
    ({"logo": {"mime": "image/png", "data_base64": base64.b64encode(b"x" * 1_100_000).decode()}}, "invalid_template"),
])
def test_a_bad_template_is_refused(client, auth, over, code):
    body = {"name": "Bad", "font": "inter", "font_size_pt": 10, "primary_color": "#000000",
            "accent_color": "#ffffff", **over}
    r = client.post("/api/p/alpha/templates", json=body, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == code


def test_a_viewer_cannot_make_a_template(client, auth):
    r = client.post("/api/p/alpha/templates", json={"name": "V", "font": "inter", "font_size_pt": 10,
                                                   "primary_color": "#000000", "accent_color": "#ffffff"},
                    headers=auth("victor"))
    assert r.status_code == 403


def test_an_editor_changes_a_template_and_can_drop_its_logo(client, auth):
    t = new_template(client, auth, name="Before", logo=LOGO)
    r = client.put(f"/api/p/alpha/templates/{t['id']}",
                   json={"name": "After", "font": "inter", "font_size_pt": 12, "primary_color": "#111111",
                         "accent_color": "#222222", "logo": None}, headers=auth("alice"))
    assert r.status_code == 200
    assert r.json()["name"] == "After" and r.json()["font_size_pt"] == 12 and r.json()["has_logo"] is False


def test_a_template_of_another_project_is_not_found(client, auth):
    t = new_template(client, auth, name="Alpha only")
    assert client.put(f"/api/p/gamma/templates/{t['id']}", json={"name": "x", "font": "inter", "font_size_pt": 10,
                      "primary_color": "#000000", "accent_color": "#ffffff"}, headers=auth("alice")).status_code == 404
    assert client.delete(f"/api/p/gamma/templates/{t['id']}", headers=auth("alice")).status_code == 404


# ── export and import ────────────────────────────────────────────────────────

def test_a_template_exports_as_one_file_with_its_logo(client, auth):
    t = new_template(client, auth, name="Bank X", font="liberation-serif", font_size_pt=11,
                     primary_color="#123456", accent_color="#abcdef", logo=LOGO)
    r = client.get(f"/api/p/alpha/templates/{t['id']}/export", headers=auth("victor"))
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"] and ".json" in r.headers["content-disposition"]
    doc = json.loads(r.content)
    assert doc == {"format": "aisc-report-template", "version": 2, "name": "Bank X", "font": "liberation-serif",
                   "font_size_pt": 11, "primary_color": "#123456", "accent_color": "#abcdef", "logo": LOGO,
                   "header_text": None, "footer_text": None, "marking": "none", "show_document_id": False}


def test_an_exported_template_imports_into_another_project(client, auth):
    t = new_template(client, auth, name="Bank X", font="liberation-serif", primary_color="#123456", logo=LOGO)
    exported = json.loads(client.get(f"/api/p/alpha/templates/{t['id']}/export", headers=auth("alice")).content)
    r = client.post("/api/p/gamma/templates/import", json=exported, headers=auth("alice"))
    assert r.status_code == 201
    imported = r.json()
    assert imported["id"] != t["id"] and imported["name"] == "Bank X" and imported["has_logo"] is True
    assert [x["name"] for x in client.get("/api/p/gamma/templates", headers=auth("alice")).json()] == ["Bank X"]


def test_importing_a_name_that_exists_keeps_both(client, auth):
    t = new_template(client, auth, name="Bank X")
    exported = json.loads(client.get(f"/api/p/alpha/templates/{t['id']}/export", headers=auth("alice")).content)
    r = client.post("/api/p/alpha/templates/import", json=exported, headers=auth("alice"))
    assert r.status_code == 201 and r.json()["name"] == "Bank X (2)"


def test_a_file_that_is_not_a_template_is_refused(client, auth):
    r = client.post("/api/p/alpha/templates/import", json={"format": "something-else", "version": 1},
                    headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "not_a_template"


def test_a_viewer_cannot_import(client, auth):
    t = new_template(client, auth, name="Bank X")
    exported = json.loads(client.get(f"/api/p/alpha/templates/{t['id']}/export", headers=auth("alice")).content)
    assert client.post("/api/p/alpha/templates/import", json=exported, headers=auth("victor")).status_code == 403


# ── a layout is saved with a template ────────────────────────────────────────

def test_a_layout_is_saved_without_a_template(client, auth):
    r = client.post("/api/p/alpha/layouts", json={"name": "No look", "system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert r.status_code == 201 and r.json()["template_id"] is None


def test_a_layout_is_not_saved_with_another_projects_template(client, auth):
    gamma_t = new_template(client, auth, slug="gamma", name="Gamma look")
    r = client.post("/api/p/alpha/layouts", json={"name": "Wrong look", "system_id": IDS["A_V2"],
                                                  "template_id": gamma_t["id"]}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "template_not_in_project"


def test_saving_changes_the_template(client, auth):
    a = new_template(client, auth, name="A")
    b = new_template(client, auth, name="B")
    lay = new_layout(client, auth, name="Styled", system_id=IDS["A_V2"], template_id=a["id"])
    assert lay["template_id"] == a["id"]
    r = put_layout(client, auth, lay, template_id=b["id"])
    assert r.status_code == 200 and r.json()["template_id"] == b["id"]
    r = put_layout(client, auth, r.json(), template_id=None)
    assert r.status_code == 200 and r.json()["template_id"] is None


def test_deleting_a_template_leaves_its_layouts_without_one(client, auth):
    t = new_template(client, auth, name="Going")
    lay = new_layout(client, auth, name="Orphan", system_id=IDS["A_V2"], template_id=t["id"])
    assert client.delete(f"/api/p/alpha/templates/{t['id']}", headers=auth("alice")).status_code == 204
    assert client.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).json()["template_id"] is None


# ── what is generated is the saved layout, in its template's look ─────────────

def test_the_pdf_is_made_in_the_saved_templates_look(client, auth, fake_renderer):
    t = new_template(client, auth, name="Bank X", font="liberation-serif", font_size_pt=11,
                     primary_color="#123456", accent_color="#abcdef", logo=LOGO)
    lay = new_layout(client, auth, name="Board pack", system_id=IDS["A_V2"], template_id=t["id"],
                     blocks=[blk("cover")])
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", headers=auth("alice"))
    assert r.status_code in (200, 201), r.text[:300]
    sent = fake_renderer.snapshots[-1]
    assert sent["mode"] == "pdf"
    assert sent["style"] == {"font": "liberation-serif", "font_size_pt": 11, "primary_color": "#123456",
                             "accent_color": "#abcdef", "logo": LOGO}


def test_a_layout_whose_template_was_deleted_is_generated_in_the_platform_look(client, auth, fake_renderer):
    t = new_template(client, auth, name="Going")
    lay = new_layout(client, auth, name="Orphan", system_id=IDS["A_V2"], template_id=t["id"])
    client.delete(f"/api/p/alpha/templates/{t['id']}", headers=auth("alice"))
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    pdf = [s for s in fake_renderer.snapshots if s["mode"] == "pdf"]
    assert pdf and "style" not in pdf[-1]


def test_the_preview_uses_the_template_and_works_without_one(client, auth, fake_renderer):
    t = new_template(client, auth, name="Look", primary_color="#123456")
    lay = new_layout(client, auth, name="Previewed", system_id=IDS["A_V2"], template_id=t["id"])
    assert client.get(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=auth("victor")).status_code == 200
    assert fake_renderer.snapshots[-1]["style"]["primary_color"] == "#123456"
    client.delete(f"/api/p/alpha/templates/{t['id']}", headers=auth("alice"))
    assert client.get(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=auth("victor")).status_code == 200
    assert "style" not in fake_renderer.snapshots[-1]


def test_editing_without_a_new_file_keeps_the_logo(client, auth):
    t = new_template(client, auth, name="Keeps", logo=LOGO)
    r = client.put(f"/api/p/alpha/templates/{t['id']}",
                   json={"name": "Keeps", "font": "inter", "font_size_pt": 10, "primary_color": "#111111",
                         "accent_color": "#222222", "keep_logo": True}, headers=auth("alice"))
    assert r.status_code == 200 and r.json()["has_logo"] is True
