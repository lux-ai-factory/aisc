"""A generated report's ledger event says which card revision the report was made of, and when it was pinned,
so the ledger alone tells "Version 1" from "Version 1, revision 2". Database tests on the bed, fake renderer."""
from __future__ import annotations

import json
import time

import jwt
import pytest

from conftest import FIXED_NOW, IDS, ISSUER, new_layout, pdb_of
from v2_fakes import client_v2, fake_v2, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

REQUEST = "a9a9a9a9-0000-4000-8000-0000000000c2"


@pytest.fixture(autouse=True)
def ledger_on(monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "record")


def witnessed(auth, key, who="alice"):
    gateway = jwt.encode({"sub": who, "preferred_username": who, "iss": ISSUER, "azp": "aisc-gateway",
                          "exp": int(time.time()) + 300}, key, algorithm="RS256")
    return {**auth(who), "X-AISC-Request-Id": REQUEST, "X-Auth-Request-Access-Token": gateway}


def generated_event(bed, report_id):
    rows = bed.rows(pdb_of("A"), "SELECT json_build_object('action', action, 'details', details,"
                                 " 'content', content) AS e FROM ledger.outbox"
                                 f" WHERE item_id = '{report_id}' ORDER BY occurred_at, event_id")
    [event] = [r["e"] if isinstance(r["e"], dict) else json.loads(r["e"]) for r in rows]
    assert event["action"] == "report.generated"
    return event


def test_the_generated_event_names_the_card_revision_the_report_was_made_of(client_v2, auth, key, bed):
    system = IDS["A_V3"]
    bed.psql(pdb_of("A"), f"UPDATE project.system SET card_revision = 2 WHERE pid = '{system}'")
    lay = new_layout(client_v2, auth, name="Revision in the ledger", blocks=[v2blk("cover")])
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": system},
                       headers=witnessed(auth, key))
    assert r.status_code == 201, r.text[:300]
    event = generated_event(bed, r.json()["id"])
    assert event["details"].get("card_version") == system
    assert event["details"].get("card_revision") == 2, event["details"]


def test_the_generated_event_records_when_the_report_was_pinned(client_v2, auth, key, bed):
    lay = new_layout(client_v2, auth, name="Pinned time in the ledger", blocks=[v2blk("cover")])
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V3"]},
                       headers=witnessed(auth, key))
    assert r.status_code == 201, r.text[:300]
    event = generated_event(bed, r.json()["id"])
    assert (event["content"] or {}).get("pinned_at") == FIXED_NOW.isoformat(), event["content"]
