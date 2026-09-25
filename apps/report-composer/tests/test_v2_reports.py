"""Generated documents of report run v2: PDF or DOCX (R-V8.14, R-V8.15, R-V8.12), the fingerprint
(R-V5.15), the document id (R-V5.14) and the template's header/footer fields in the snapshot (R-V5.11
composer side). Database tests, v2 fake renderer.
"""
import json

import pytest

from conftest import IDS, error_code, new_layout, new_template, pdb_of
from v2_fakes import DOCX, FINGERPRINT, client_v2, fake_v2, unique, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def layout(client, auth, **body):
    body.setdefault("name", "Quarterly report")
    body.setdefault("system_id", IDS["A_V2"])
    body.setdefault("blocks", [v2blk("cover"), v2blk("free_text", text="x")])
    return new_layout(client, auth, **body)


def generate(client, auth, lay, **body):
    return client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json=body, headers=auth("alice"))


# ── R-V8.14 format ──────────────────────────────────────────────────────────

def test_r_v8_14_docx_is_asked_of_the_renderer(client_v2, auth, fake_v2):
    lay = layout(client_v2, auth)
    r = generate(client_v2, auth, lay, format="docx")
    assert r.status_code == 201, r.text[:300]
    assert fake_v2.snapshots[-1]["mode"] == "docx"


def test_r_v8_14_absent_format_is_pdf(client_v2, auth, fake_v2):
    lay = layout(client_v2, auth)
    assert generate(client_v2, auth, lay).status_code == 201
    assert fake_v2.snapshots[-1]["mode"] == "pdf"
    assert fake_v2.snapshots[-1].get("snapshot_version") == 2


def test_r_v8_14_an_unknown_format_is_refused(client_v2, auth):
    lay = layout(client_v2, auth)
    r = generate(client_v2, auth, lay, format="odt")
    assert r.status_code == 422 and error_code(r) == "invalid_request"


# ── R-V8.15 storage, download, list ─────────────────────────────────────────

def test_r_v8_15_docx_is_stored_with_its_format_and_downloads_as_word(client_v2, auth, bed):
    lay = layout(client_v2, auth)
    rid = generate(client_v2, auth, lay, format="docx").json()["id"]
    fmt = bed.scalar(pdb_of("A"), f"SELECT format FROM report_composer.generated_report WHERE id = '{rid}'")
    assert fmt == "docx"
    r = client_v2.get(f"/api/p/alpha/reports/{rid}/download", headers=auth("victor"))
    assert r.status_code == 200 and r.content == DOCX
    assert r.headers["content-type"] == DOCX_TYPE
    assert 'filename="alpha-v2-quarterly-report-20260920-1030.docx"' in r.headers["content-disposition"]


def test_r_v8_15_the_old_pdf_route_answers_404_for_a_docx(client_v2, auth):
    lay = layout(client_v2, auth)
    rid = generate(client_v2, auth, lay, format="docx").json()["id"]
    assert client_v2.get(f"/api/p/alpha/reports/{rid}/pdf", headers=auth("alice")).status_code == 404


def test_r_v8_15_download_serves_a_pdf_too(client_v2, auth):
    from conftest import PDF

    lay = layout(client_v2, auth)
    rid = generate(client_v2, auth, lay).json()["id"]
    r = client_v2.get(f"/api/p/alpha/reports/{rid}/download", headers=auth("victor"))
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"].endswith('.pdf"')
    assert client_v2.get(f"/api/p/alpha/reports/{rid}/pdf", headers=auth("victor")).status_code == 200


def test_r_v8_15_the_reports_list_shows_format_and_fingerprint(client_v2, auth):
    lay = layout(client_v2, auth)
    generate(client_v2, auth, lay, format="docx")
    generate(client_v2, auth, lay)
    rows = client_v2.get(f"/api/p/alpha/layouts/{lay['id']}/reports", headers=auth("victor")).json()
    assert sorted(str(r.get("format")) for r in rows) == ["docx", "pdf"]
    assert all(r.get("fingerprint") == FINGERPRINT for r in rows)


def test_r_v8_15_the_editor_page_lists_the_format(client_v2, auth):
    lay = layout(client_v2, auth)
    generate(client_v2, auth, lay, format="docx")
    page = client_v2.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text
    assert "DOCX" in page and f"/reports/" in page and "/download" in page


# ── R-V8.12 the size rule for both formats ──────────────────────────────────

def test_r_v8_12_a_document_over_25_mb_is_not_stored(client_v2, auth, fake_v2):
    fake_v2.docx = b"PK\x03\x04" + b"0" * (25 * 1024 * 1024 + 1)
    lay = layout(client_v2, auth)
    r = generate(client_v2, auth, lay, format="docx")
    assert error_code(r) == "pdf_too_large"
    assert r.json()["error"]["message"].startswith("The document is larger than 25 MB and was not stored")


# ── R-V5.15 the fingerprint is stored and shown ─────────────────────────────

def test_r_v5_15_the_fingerprint_is_stored(client_v2, auth, bed):
    lay = layout(client_v2, auth)
    rid = generate(client_v2, auth, lay).json()["id"]
    got = bed.scalar(pdb_of("A"), f"SELECT fingerprint FROM report_composer.generated_report WHERE id = '{rid}'")
    assert got == FINGERPRINT


def test_r_v5_15_the_editor_shows_the_fingerprint_next_to_the_sha256(client_v2, auth):
    lay = layout(client_v2, auth)
    generate(client_v2, auth, lay)
    page = client_v2.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice")).text
    assert FINGERPRINT[:12] in page


# ── R-V5.14 the document id is the report's id ──────────────────────────────

def test_r_v5_14_the_document_id_is_the_generated_report_id(client_v2, auth, fake_v2):
    lay = layout(client_v2, auth)
    rid = generate(client_v2, auth, lay).json()["id"]
    assert (fake_v2.snapshots[-1].get("document") or {}).get("id") == rid


# ── R-V5.10/R-V5.11 composer side: the template's header/footer fields reach the renderer ──

def test_r_v5_11_the_style_carries_header_footer_marking_and_document_id(client_v2, auth, fake_v2):
    t = new_template(client_v2, auth, name=unique("Marked"), header_text="{project} v{version}",
                     footer_text="Internal use", marking="confidential", show_document_id=True)
    lay = layout(client_v2, auth, template_id=t["id"])
    assert generate(client_v2, auth, lay).status_code == 201
    style = fake_v2.snapshots[-1]["style"]
    assert (style.get("header_text"), style.get("footer_text"), style.get("marking"), style.get("show_document_id")) == \
        ("{project} v{version}", "Internal use", "confidential", True)


def test_r_v5_16_a_default_template_sends_the_old_look_and_default_fields(client_v2, auth, fake_v2):
    t = new_template(client_v2, auth, name=unique("Plain"), font="inter", font_size_pt=10,
                     primary_color="#000fdf", accent_color="#ff007e")
    lay = layout(client_v2, auth, template_id=t["id"])
    generate(client_v2, auth, lay)
    style = fake_v2.snapshots[-1]["style"]
    old = {"font": "inter", "font_size_pt": 10, "primary_color": "#000fdf", "accent_color": "#ff007e"}
    assert {k: style[k] for k in old} == old
    assert style.get("header_text") is None and style.get("footer_text") is None
    assert style.get("marking", "none") == "none" and style.get("show_document_id", False) is False
