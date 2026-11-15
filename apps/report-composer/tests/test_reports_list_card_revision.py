"""The generated reports list and the sandbox Report tile say which card revision each report is pinned to.
The layout's own revision is labelled as the layout's, so it does not read as the card's. Database tests,
fake renderer."""
from __future__ import annotations

import pytest

from conftest import IDS, new_layout, pdb_of
from v2_fakes import client_v2, fake_v2, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def soup(html):
    from bs4 import BeautifulSoup
    return BeautifulSoup(html, "html.parser")


def corrected_to(bed, revision):
    bed.psql(pdb_of("A"), f"UPDATE project.system SET card_revision = {revision} WHERE pid = '{IDS['A_V3']}'")


def generate(client, auth, layout_id):
    r = client.post(f"/api/p/alpha/layouts/{layout_id}/reports", json={"system_id": IDS["A_V3"]},
                    headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    return r.json()["id"]


def reports_table(client, auth, layout_id):
    return soup(client.get(f"/p/alpha/layouts/{layout_id}", headers=auth("alice")).text).select_one(
        "table[data-reports]")


def test_the_reports_list_names_the_layout_revision_column_as_the_layouts(client_v2, auth):
    lay = new_layout(client_v2, auth, name="Column names", blocks=[v2blk("cover")])
    generate(client_v2, auth, lay["id"])
    headers = [th.get_text(strip=True) for th in reports_table(client_v2, auth, lay["id"]).select("thead th")]
    assert "Layout revision" in headers, headers


def test_the_reports_list_shows_the_card_revision_a_report_is_pinned_to(client_v2, auth, bed):
    corrected_to(bed, 2)
    lay = new_layout(client_v2, auth, name="Card revision shown", blocks=[v2blk("cover")])
    generate(client_v2, auth, lay["id"])
    row = reports_table(client_v2, auth, lay["id"]).select("tbody tr")[0]
    text = row.get_text(" ", strip=True)
    assert "Version 3, revision 2" in text, text


def test_the_sandbox_summary_names_the_latest_reports_card_revision(client_v2, auth, bed):
    corrected_to(bed, 2)
    lay = new_layout(client_v2, auth, name="Summary revision", blocks=[v2blk("cover")])
    generate(client_v2, auth, lay["id"])
    latest = client_v2.get(f"/api/p/alpha/reports?system_id={IDS['A_V3']}", headers=auth("alice")).json()["latest"]
    assert latest.get("card_revision") == 2, latest


def test_the_sandbox_summary_marks_a_latest_report_of_an_earlier_card_revision(client_v2, auth, bed):
    corrected_to(bed, 1)
    lay = new_layout(client_v2, auth, name="Summary stale", blocks=[v2blk("cover")])
    generate(client_v2, auth, lay["id"])
    corrected_to(bed, 2)
    latest = client_v2.get(f"/api/p/alpha/reports?system_id={IDS['A_V3']}", headers=auth("alice")).json()["latest"]
    assert latest.get("of_an_earlier_card_revision") is True, latest
