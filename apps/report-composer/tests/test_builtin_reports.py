"""A built-in layout generates reports exactly like the project's own (2026-10-06): Download report on its
page, PDF or Word, its reports listed under it with Download PDF and Download Word. A report belongs to a
layout of the project, so each built-in has one record per project, made at its first report and kept in
step with the built-in at every report; it is not one of the project's layouts (not listed, its name stays
free, never edited). Database tests, fake renderer."""
import pytest

from conftest import IDS, PDF, new_layout, pdb_of
from v2_fakes import DOCX, client_v2, fake_v2  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

B = "builtin-summary"


def generate(client_v2, auth, fmt="pdf", who="alice"):
    return client_v2.post(f"/api/p/alpha/layouts/{B}/reports", json={"system_id": IDS["A_V2"], "format": fmt},
                       headers=auth(who))


def test_a_built_in_generates_a_pdf_report_listed_under_it(client_v2, auth):
    r = generate(client_v2, auth)
    assert r.status_code == 201, r.text
    listed = client_v2.get(f"/api/p/alpha/layouts/{B}/reports", headers=auth("victor")).json()
    assert [x["id"] for x in listed] == [r.json()["id"]] and listed[0]["has_pdf"] is True
    pdf = client_v2.get(f"/api/p/alpha/reports/{r.json()['id']}/pdf", headers=auth("victor"))
    assert pdf.status_code == 200 and pdf.content == PDF


def test_a_built_in_generates_a_word_report_with_its_pdf(client_v2, auth):
    made = generate(client_v2, auth, "docx").json()
    assert client_v2.get(f"/api/p/alpha/reports/{made['id']}/download", headers=auth("victor")).content == DOCX
    assert client_v2.get(f"/api/p/alpha/reports/{made['id']}/pdf", headers=auth("victor")).content == PDF


def test_its_reports_share_one_record_that_is_not_a_project_layout(client_v2, auth, bed):
    generate(client_v2, auth)
    generate(client_v2, auth, "docx")
    rows = bed.rows(pdb_of("A"), "SELECT name FROM report_composer.layout WHERE builtin_id = 'builtin-summary'")
    assert len(rows) == 1
    assert [x["name"] for x in client_v2.get("/api/p/alpha/layouts", headers=auth("alice")).json()] == []
    # its name stays free for a layout of the project's own
    assert new_layout(client_v2, auth, name=rows[0]["name"])["name"] == rows[0]["name"]


def test_the_record_cannot_be_changed_or_deleted_as_a_layout(client_v2, auth, bed):
    generate(client_v2, auth)
    lid = bed.rows(pdb_of("A"), "SELECT id FROM report_composer.layout WHERE builtin_id = 'builtin-summary'")[0]["id"]
    assert client_v2.get(f"/api/p/alpha/layouts/{lid}", headers=auth("alice")).status_code == 404
    assert client_v2.delete(f"/api/p/alpha/layouts/{lid}", headers=auth("alice")).status_code == 404


def test_a_viewer_cannot_generate_one(client_v2, auth):
    assert generate(client_v2, auth, who="victor").status_code == 403


def test_the_built_ins_page_has_generate_and_its_reports(client_v2, auth):
    made = generate(client_v2, auth, "docx").json()
    page = client_v2.get(f"/p/alpha/layouts/{B}", headers=auth("alice")).text
    assert f"/layouts/{B}/download-report" in page and "Download report" in page
    assert f'/api/p/alpha/reports/{made["id"]}/pdf"' in page and "Download PDF" in page and "Download Word" in page
    assert "Download report" not in client_v2.get(f"/p/alpha/layouts/{B}", headers=auth("victor")).text


def test_the_generate_form_works_for_a_built_in(client_v2, auth):
    assert client_v2.get(f"/p/alpha/layouts/{B}/generate", headers=auth("alice")).status_code == 200
    r = client_v2.post(f"/p/alpha/layouts/{B}/generate", headers=auth("alice"), follow_redirects=False,
                    data={"system_id": IDS["A_V2"], "format": "pdf"})
    assert r.status_code == 303 and r.headers["location"].endswith(f"/p/alpha/layouts/{B}#reports")


def test_the_layouts_page_shows_a_built_ins_last_report(client_v2, auth):
    generate(client_v2, auth)
    page = client_v2.get("/p/alpha/", headers=auth("victor")).text
    row = page[page.index(f'data-layout="{B}"'):]
    row = row[:row.index("</tr>")]
    assert "(done)" in row
