"""Every generated report can be downloaded as PDF (2026-10-05). A Word report gets its PDF copy in the
same generation, from the same snapshot, so both show the same data; a PDF report is its own PDF.
Database tests, fake renderer."""
import hashlib

import pytest

from conftest import DOCX, IDS, PDF, blk, new_layout, pdb_of

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def word_report(client, auth):
    lay = new_layout(client, auth, name="Quarterly report", system_id=IDS["A_V2"],
                     blocks=[blk("cover"), blk("free_text", text="x")])
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"], "format": "docx"},
                    headers=auth("alice"))
    assert r.status_code == 201, r.text
    return lay, r.json()


def test_a_word_report_is_rendered_as_pdf_too_from_the_same_snapshot(client, auth, fake_renderer, bed):
    _, made = word_report(client, auth)
    docx_sent, pdf_sent = fake_renderer.snapshots[-2:]
    assert (docx_sent["mode"], pdf_sent["mode"]) == ("docx", "pdf")
    assert {k: v for k, v in pdf_sent.items() if k != "mode"} == {k: v for k, v in docx_sent.items() if k != "mode"}
    stored = bed.rows(pdb_of("A"), "SELECT encode(pdf, 'hex') AS pdf, encode(pdf_copy, 'hex') AS pdf_copy,"
                                   " pdf_copy_sha256 FROM report_composer.generated_report"
                                   f" WHERE id = '{made['id']}'")[0]
    assert stored["pdf"] == DOCX.hex() and stored["pdf_copy"] == PDF.hex()
    assert stored["pdf_copy_sha256"] == hashlib.sha256(PDF).hexdigest()


def test_the_pdf_route_serves_a_word_reports_copy_and_download_still_the_word_file(client, auth):
    _, made = word_report(client, auth)
    pdf = client.get(f"/api/p/alpha/reports/{made['id']}/pdf", headers=auth("victor"))
    assert pdf.status_code == 200 and pdf.content == PDF and pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].endswith('.pdf"')
    word = client.get(f"/api/p/alpha/reports/{made['id']}/download", headers=auth("victor"))
    assert word.status_code == 200 and word.content == DOCX


def test_the_list_says_which_reports_have_a_pdf(client, auth, fake_renderer):
    lay, made = word_report(client, auth)
    fake_renderer.fail_modes = {"pdf"}
    failed_copy = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports",
                              json={"system_id": IDS["A_V2"], "format": "docx"}, headers=auth("alice")).json()
    fake_renderer.fail_modes = set()
    listed = {r["id"]: r for r in client.get(f"/api/p/alpha/layouts/{lay['id']}/reports", headers=auth("victor")).json()}
    assert listed[made["id"]]["has_pdf"] is True
    assert failed_copy["status"] == "done" and listed[failed_copy["id"]]["has_pdf"] is False
    assert client.get(f"/api/p/alpha/reports/{failed_copy['id']}/pdf", headers=auth("victor")).status_code == 404


def test_the_pages_offer_download_pdf_for_every_report(client, auth):
    lay, made = word_report(client, auth)
    pdf_made = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]},
                           headers=auth("alice")).json()
    editor = client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("victor")).text
    client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice"))
    deleted = client.get("/p/alpha/", headers=auth("victor")).text      # Reports of deleted layouts
    for page in (editor, deleted):
        assert f'/api/p/alpha/reports/{made["id"]}/pdf"' in page and f'/api/p/alpha/reports/{made["id"]}/download"' in page
        assert f'/api/p/alpha/reports/{pdf_made["id"]}/pdf"' in page
        assert page.count("Download PDF") >= 2 and page.count("Download Word") >= 1


def test_downloading_the_copy_is_recorded_with_its_own_hash(client, auth, bed, monkeypatch):
    from report_composer import anchor
    from test_ledger import outbox

    monkeypatch.setenv("LEDGER_MODE", "record")
    monkeypatch.setattr(anchor, "fetch", lambda request, project: None)
    _, made = word_report(client, auth)
    client.get(f"/api/p/alpha/reports/{made['id']}/pdf", headers=auth("victor"))
    downloaded = [e for e in outbox(bed, made["id"]) if e["action"] == "report.downloaded"]
    assert downloaded[-1]["details"] == {"document_sha256": hashlib.sha256(PDF).hexdigest(), "format": "pdf"}
