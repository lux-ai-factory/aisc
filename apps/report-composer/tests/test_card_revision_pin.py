"""A report is pinned to the card revision it was made from, and to the time it was generated, so it can be
made again exactly. The built-in layouts end with the Amendments block, in the appendix."""
import json
from datetime import datetime

import pytest

from conftest import BLOCK_TYPES, FIXED_NOW, IDS, new_layout, pdb_of
from v2_fakes import client_v2, fake_v2, v2blk  # noqa: F401


def _snapshot(**changes):
    from report_composer.reports import snapshot_of
    from types import SimpleNamespace

    caller = SimpleNamespace(username="alice", email=None, subject="alice")
    layout = {"id": "l", "name": "L", "revision": 1, "blocks": []}
    args = {"system_id": "s", "card_revision": 1, "pinned_at": FIXED_NOW}
    args.update(changes)
    return snapshot_of({"pid": "p"}, layout, "pdf", caller, **args)


def test_snapshot_pins_the_versions_current_card_revision():
    assert _snapshot(card_revision=2)["card_revision"] == 2


def test_snapshot_pins_the_generation_time():
    snap = _snapshot(pinned_at=FIXED_NOW)
    assert snap["pinned_at"] == "2026-09-20T10:30:00+00:00"
    assert datetime.fromisoformat(snap["pinned_at"]).tzinfo is not None


@pytest.mark.db
@pytest.mark.usefixtures("clean_layouts")
def test_a_report_pins_the_revision_and_the_time_of_its_generation(client_v2, auth, fake_v2, bed):
    bed.psql(pdb_of("A"), f"UPDATE project.system SET card_revision = 2 WHERE pid = '{IDS['A_V3']}'")
    lay = new_layout(client_v2, auth, name="Pinned", blocks=[v2blk("cover")])
    r = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V3"]},
                       headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    sent = fake_v2.snapshots[-1]
    assert sent["card_revision"] == 2 and sent["pinned_at"] == FIXED_NOW.isoformat()
    stored = json.loads(bed.scalar(pdb_of("A"), f"SELECT snapshot::text FROM report_composer.generated_report"
                                                f" WHERE id = '{r.json()['id']}'"))
    assert (stored["card_revision"], stored["pinned_at"]) == (2, FIXED_NOW.isoformat())
    created = bed.scalar(pdb_of("A"), f"SELECT created_at FROM report_composer.generated_report"
                                      f" WHERE id = '{r.json()['id']}'")
    assert datetime.fromisoformat(stored["pinned_at"]) == datetime.fromisoformat(created)


@pytest.mark.db
@pytest.mark.usefixtures("clean_layouts")
def test_a_stored_report_regenerates_with_its_own_pinned_revision_after_a_later_correction(
        client_v2, auth, fake_v2, bed):
    bed.psql(pdb_of("A"), f"UPDATE project.system SET card_revision = 1 WHERE pid = '{IDS['A_V3']}'")
    lay = new_layout(client_v2, auth, name="Pinned later", blocks=[v2blk("cover")])
    rid = client_v2.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"system_id": IDS["A_V3"]},
                         headers=auth("alice")).json()["id"]
    bed.psql(pdb_of("A"), f"UPDATE project.system SET card_revision = 2 WHERE pid = '{IDS['A_V3']}'")
    before = bed.scalar(pdb_of("A"), f"SELECT snapshot::text FROM report_composer.generated_report WHERE id = '{rid}'")
    # the PDF copy and every later render use the stored snapshot, not a recomputed one
    from report_composer import reports
    copy = []
    reports._pdf_copy(type("R", (), {"render": lambda self, s: copy.append(s) or {"pdf_base64": ""}})(),
                      json.loads(before))
    assert copy[0]["card_revision"] == 1 and copy[0]["pinned_at"] == FIXED_NOW.isoformat()
    assert bed.scalar(pdb_of("A"), f"SELECT snapshot::text FROM report_composer.generated_report"
                                   f" WHERE id = '{rid}'") == before


def test_built_in_layouts_end_with_an_amendments_block_in_the_appendix():
    from report_composer import builtin_layouts
    for layout in builtin_layouts.all_layouts(BLOCK_TYPES):
        kinds = [b["block_type"] for b in layout["blocks"]]
        assert kinds[-1] == "amendments", layout["id"]
        assert "appendix" in kinds[:-1], layout["id"]

