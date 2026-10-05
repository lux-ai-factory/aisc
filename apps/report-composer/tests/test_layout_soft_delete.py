"""A deleted layout keeps its reports.

Deleting a layout hides it: it leaves the list and every layout route, and its name is free again. Its
generated reports stay, each still downloadable, listed on the layouts page under "Reports of deleted
layouts". The database refuses a hard delete of a layout that has reports (the key is RESTRICT), so no
code path can take them again. Database tests on the bed, with a fake renderer."""
from __future__ import annotations

import pytest

from conftest import IDS, blk, new_layout, pdb_of, put_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _with_report(client, auth, name="Doomed"):
    lay = new_layout(client, auth, name=name, blocks=[blk("free_text", text="x")])
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice"))
    assert r.status_code == 201, r.text
    return lay, r.json()["id"]


def test_a_deleted_layout_leaves_every_layout_route(client, auth):
    lay, _ = _with_report(client, auth)
    assert client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).status_code == 204
    assert lay["id"] not in [l["id"] for l in client.get("/api/p/alpha/layouts", headers=auth("alice")).json()]
    base = f"/api/p/alpha/layouts/{lay['id']}"
    assert client.get(base, headers=auth("alice")).status_code == 404
    assert put_layout(client, auth, lay).status_code == 404
    assert client.post(f"{base}/duplicate", json={}, headers=auth("alice")).status_code == 404
    assert client.post(f"{base}/reports", json={"system_id": IDS["A_V2"]}, headers=auth("alice")).status_code == 404
    assert client.get(f"{base}/reports", headers=auth("alice")).status_code == 404
    assert client.delete(base, headers=auth("alice")).status_code == 404       # deleted once


def test_its_reports_stay_and_are_listed(client, auth):
    lay, report_id = _with_report(client, auth, name="Gone but kept")
    client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice"))
    assert client.get(f"/api/p/alpha/reports/{report_id}/pdf", headers=auth("victor")).status_code == 200
    r = client.get("/api/p/alpha/deleted-layouts", headers=auth("victor"))
    assert r.status_code == 200
    [gone] = [d for d in r.json() if d["id"] == lay["id"]]
    assert gone["name"] == "Gone but kept" and gone["deleted_at"]
    assert [x["id"] for x in gone["reports"]] == [report_id]


def test_a_deleted_layout_without_reports_is_not_listed(client, auth):
    lay = new_layout(client, auth, name="Empty and gone")
    client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice"))
    assert lay["id"] not in [d["id"] for d in client.get("/api/p/alpha/deleted-layouts", headers=auth("alice")).json()]


def test_the_layouts_page_offers_their_downloads(client, auth):
    lay, report_id = _with_report(client, auth, name="Page kept")
    client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice"))
    page = client.get("/p/alpha/", headers=auth("victor"))
    assert page.status_code == 200
    assert "Reports of deleted layouts" in page.text and "Page kept" in page.text
    assert f"/api/p/alpha/reports/{report_id}/download" in page.text


def test_its_name_is_free_again(client, auth):
    lay = new_layout(client, auth, name="Reused name")
    client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice"))
    again = new_layout(client, auth, name="Reused name")
    assert again["id"] != lay["id"]


def test_the_database_refuses_a_hard_delete_that_would_take_reports(client, auth, bed):
    lay, _ = _with_report(client, auth, name="Hard")
    r = bed.psql(pdb_of("A"), f"DELETE FROM report_composer.layout WHERE id = '{lay['id']}'", check=False)
    assert r.returncode != 0 and "foreign key" in (r.stderr or "").lower()
