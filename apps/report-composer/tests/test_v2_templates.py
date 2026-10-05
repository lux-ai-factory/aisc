"""Template fields: header text, footer text, marking, document id. Database tests, v2 fake renderer.
"""
import json

import pytest

from conftest import error_code, new_template
from v2_fakes import client_v2, fake_v2, unique  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

LOOK = {"font": "inter", "font_size_pt": 10, "primary_color": "#000fdf", "accent_color": "#ff007e"}


def soup(html):
    from bs4 import BeautifulSoup

    return BeautifulSoup(html, "html.parser")


def test_r_v5_10_the_four_fields_are_saved_and_shown(client_v2, auth):
    t = new_template(client_v2, auth, name=unique("Marked"), header_text="{project}, v{version}",
                     footer_text="Draft for {layout}", marking="strictly_confidential", show_document_id=True)
    assert (t.get("header_text"), t.get("footer_text"), t.get("marking"), t.get("show_document_id")) == \
        ("{project}, v{version}", "Draft for {layout}", "strictly_confidential", True)
    listed = next(x for x in client_v2.get("/api/p/alpha/templates", headers=auth("victor")).json() if x["id"] == t["id"])
    assert listed.get("marking") == "strictly_confidential"


def test_r_c_6_template_fields_default_to_todays_behaviour(client_v2, auth):
    t = new_template(client_v2, auth, name=unique("Default"))
    assert {k: t.get(k, "absent") for k in ("header_text", "footer_text", "marking", "show_document_id")} == \
        {"header_text": None, "footer_text": None, "marking": "none", "show_document_id": False}


@pytest.mark.parametrize("over", [
    {"header_text": "x" * 121},
    {"footer_text": "y" * 121},
    {"marking": "secret"},
    {"show_document_id": "yes"},
])
def test_r_v5_10_bad_fields_are_refused(client_v2, auth, over):
    r = client_v2.post("/api/p/alpha/templates", json={"name": unique("Bad"), **LOOK, **over}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "invalid_template"
    assert any(d.get("pointer") == "/" + next(iter(over)) for d in r.json()["error"]["details"])


@pytest.mark.parametrize("marking", ["none", "public", "internal", "confidential", "strictly_confidential"])
def test_r_v5_10_the_five_markings(client_v2, auth, marking):
    r = client_v2.post("/api/p/alpha/templates", json={"name": unique("M"), **LOOK, "marking": marking},
                       headers=auth("alice"))
    assert r.status_code == 201 and r.json().get("marking") == marking


def test_r_v5_10_export_is_version_2_with_the_fields(client_v2, auth):
    t = new_template(client_v2, auth, name=unique("Exported"), header_text="H", footer_text="F", marking="internal",
                     show_document_id=True)
    doc = json.loads(client_v2.get(f"/api/p/alpha/templates/{t['id']}/export", headers=auth("alice")).content)
    assert doc["version"] == 2
    assert (doc.get("header_text"), doc.get("footer_text"), doc.get("marking"), doc.get("show_document_id")) == \
        ("H", "F", "internal", True)


def test_r_v5_10_import_accepts_version_1_with_defaults(client_v2, auth):
    old = {"format": "aisc-report-template", "version": 1, "name": unique("Old file"), **LOOK, "logo": None}
    r = client_v2.post("/api/p/alpha/templates/import", json=old, headers=auth("alice"))
    assert r.status_code == 201
    assert (r.json().get("marking"), r.json().get("show_document_id"), r.json().get("header_text", "absent")) == \
        ("none", False, None)


def test_r_v5_10_import_accepts_version_2(client_v2, auth):
    new = {"format": "aisc-report-template", "version": 2, "name": unique("New file"), **LOOK, "logo": None,
           "header_text": "H2", "footer_text": None, "marking": "public", "show_document_id": False}
    r = client_v2.post("/api/p/alpha/templates/import", json=new, headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert (r.json().get("header_text"), r.json().get("marking")) == ("H2", "public")


def test_r_v5_17_the_template_form_has_the_new_fields(client_v2, auth):
    doc = soup(client_v2.get("/p/alpha/templates?new=1", headers=auth("alice")).text)
    form = doc.find(attrs={"data-control": "new-template"})
    assert form is not None
    assert form.find("input", attrs={"name": "header_text"}) is not None
    assert form.find("input", attrs={"name": "footer_text"}) is not None
    marking = form.find("select", attrs={"name": "marking"})
    assert marking is not None
    assert [o.get_text(strip=True) for o in marking.find_all("option")] == \
        ["None", "Public", "Internal", "Confidential", "Strictly confidential"]
    assert "{project}" in form.get_text() and "{version}" in form.get_text()     # the placeholder help line
    more = form.find("details")
    assert more is not None and more.find("summary").get_text(strip=True) == "More options"
    assert more.find("input", attrs={"name": "show_document_id"}) is not None
    assert "Print the document id and fingerprint" in more.get_text()
