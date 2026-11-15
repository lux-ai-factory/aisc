"""With the ledger enforced, a state-changing request that reached the composer without a witnessed request
id (it did not pass the gateway) is refused before it commits: an unrecorded write cannot land. Database
tests on the bed."""
from __future__ import annotations

import pytest

from conftest import blk, new_layout, pdb_of, put_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def revisions(bed, layout_id):
    return int(bed.scalar(pdb_of("A"), "SELECT count(*) FROM report_composer.layout_revision"
                                       f" WHERE layout_id = '{layout_id}'"))


def test_a_layout_save_without_a_witnessed_request_is_refused_and_not_committed(client, auth, bed, monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "record")
    lay = new_layout(client, auth, name="Unwitnessed save", blocks=[blk("free_text", text="one")])
    monkeypatch.setenv("LEDGER_MODE", "enforce")
    r = put_layout(client, auth, lay, blocks=[blk("free_text", text="two")])
    assert r.status_code >= 400, f"an unwitnessed layout save was taken: {r.status_code}"
    assert revisions(bed, lay["id"]) == 1


def test_a_layout_delete_without_a_witnessed_request_is_refused(client, auth, bed, monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "record")
    lay = new_layout(client, auth, name="Unwitnessed delete")
    monkeypatch.setenv("LEDGER_MODE", "enforce")
    r = client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice"))
    assert r.status_code >= 400, f"an unwitnessed layout delete was taken: {r.status_code}"
    assert bed.scalar(pdb_of("A"), "SELECT deleted_at IS NULL FROM report_composer.layout"
                                   f" WHERE id = '{lay['id']}'") in (True, "t")


def test_a_layout_create_without_a_witnessed_request_is_refused(client, auth, monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "enforce")
    r = client.post("/api/p/alpha/layouts", json={"name": "Unwitnessed create"}, headers=auth("alice"))
    assert r.status_code >= 400, f"an unwitnessed layout create was taken: {r.status_code}"
