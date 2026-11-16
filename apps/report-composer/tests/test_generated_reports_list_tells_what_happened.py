"""The Generated reports list of a layout says what happened to each report: when it was made, in a time that
names its zone; a generation cut off half way is not "running" forever; a Word report without its PDF copy says
why there is no Download PDF. Generate and download refuses to make a report of a revision other than the one
the person was looking at. Database tests, fake renderer."""
from datetime import timedelta

import pytest
from bs4 import BeautifulSoup

from conftest import FIXED_NOW, IDS, blk, new_layout, pdb_of, put_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _layout(client, auth):
    return new_layout(client, auth, name="Quarterly report", system_id=IDS["A_V2"],
                      blocks=[blk("cover"), blk("free_text", text="x")])


def _generate(client, auth, layout_id, fmt="pdf"):
    r = client.post(f"/api/p/alpha/layouts/{layout_id}/reports", json={"system_id": IDS["A_V2"], "format": fmt},
                    headers=auth("alice"))
    assert r.status_code == 201, r.text
    return r.json()


def _rows(client, auth, layout_id):
    page = BeautifulSoup(client.get(f"/p/alpha/layouts/{layout_id}", headers=auth("alice")).text, "html.parser")
    table = page.find("table", attrs={"data-reports": True})
    assert table is not None, "no Generated reports table"
    return table.find("tbody").find_all("tr")


def test_the_time_a_report_was_made_names_its_zone(client, auth):
    lay = _layout(client, auth)
    _generate(client, auth, lay["id"])
    created = _rows(client, auth, lay["id"])[0].find_all("td")[0]
    stamp = created.find("time")
    zoned = "UTC" in created.get_text() or (stamp is not None and (stamp.get("datetime") or "").endswith(
        ("Z", "+00:00")))
    assert zoned, f"the Created time names no zone: {created.get_text()!r}"


def test_a_generation_cut_off_half_way_is_not_running_forever(client, auth, bed):
    lay = _layout(client, auth)
    made = _generate(client, auth, lay["id"])
    long_ago = (FIXED_NOW - timedelta(hours=2)).isoformat()
    # what a composer restart during the render leaves: the row inserted as running, never finished
    bed.psql(pdb_of("A"), "UPDATE report_composer.generated_report SET status = 'running', pdf = NULL,"
                          f" sha256 = NULL, finished_at = NULL, created_at = '{long_ago}' WHERE id = '{made['id']}'")
    listed = {r["id"]: r for r in client.get(f"/api/p/alpha/layouts/{lay['id']}/reports",
                                             headers=auth("alice")).json()}
    assert listed[made["id"]]["status"] != "running", \
        f"a report cut off two hours ago is still listed as running: {listed[made['id']]['status']!r}"
    shown = _rows(client, auth, lay["id"])[0].get_text(" ", strip=True)
    assert "running" not in shown, f"the editor still says running: {shown!r}"


def test_a_word_report_without_its_pdf_copy_says_why(client, auth, fake_renderer):
    lay = _layout(client, auth)
    fake_renderer.fail_modes = {"pdf"}
    made = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"], "format": "docx"},
                       headers=auth("alice"))
    fake_renderer.fail_modes = set()
    assert made.status_code == 201, made.text
    shown = _rows(client, auth, lay["id"])[0].get_text(" ", strip=True)
    assert "Download PDF" not in shown
    assert "PDF version not available" in shown or "no PDF" in shown.lower(), \
        f"the list gives no reason for the missing Download PDF: {shown!r}"
    answer = made.json()
    assert any(k.startswith("pdf_copy") for k in answer), \
        f"the generate answer does not say the PDF copy failed: {sorted(answer)}"


def test_generate_and_download_refuses_a_revision_other_than_the_one_shown(client, auth):
    lay = _layout(client, auth)
    shown_revision = lay["revision"]
    put_layout(client, auth, lay, name="Renamed meanwhile")           # the stored layout moved on
    r = client.post(f"/p/alpha/layouts/{lay['id']}/download-report", headers=auth("alice"),
                    data={"system_id": IDS["A_V2"], "format": "pdf", "revision": str(shown_revision)},
                    follow_redirects=False)
    assert r.headers.get("content-type") != "application/pdf", \
        "a report of the newer stored revision was made for a page that showed an older one"
    listed = client.get(f"/api/p/alpha/layouts/{lay['id']}/reports", headers=auth("alice")).json()
    assert listed == [], f"a report was stored anyway: {listed}"
