"""Reports generated for a chosen selection (report modules spec 2026-09-28, section 6)."""
import pytest

from conftest import IDS, blk, new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def _generate(client, auth, lay, **choice):
    return client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={"format": "pdf", **choice},
                       headers=auth("alice"))


def test_a_report_needs_a_version(client, auth):
    lay = new_layout(client, auth, name="Needs", blocks=[blk("cover")])
    r = _generate(client, auth, lay)
    assert r.status_code == 422 and "system_id" in r.text


def test_the_selection_is_sent_and_recorded(client, auth, fake_renderer):
    lay = new_layout(client, auth, name="Chosen", blocks=[blk("cover")])
    r = _generate(client, auth, lay, system_id=IDS["A_V2"], period_from="2026-09-10", period_to="2026-09-10",
                  other_versions=True)
    assert r.status_code == 201, r.text
    snap = fake_renderer.snapshots[-1]
    assert snap["snapshot_version"] == 3 and snap["system_id"] == IDS["A_V2"]
    assert snap["selection"] == {"period_from": "2026-09-10T00:00:00+00:00",
                                 "period_to": "2026-09-11T00:00:00+00:00", "other_versions": True,
                                 "compare_to": None}
    row = client.get(f"/api/p/alpha/layouts/{lay['id']}/reports", headers=auth("alice")).json()[0]
    assert (row["system_number"], row["period_from"][:10], row["last_day"], row["other_versions"]) == \
        (2, "2026-09-10", "2026-09-10", True)


def test_a_version_of_another_project_is_refused(client, auth):
    lay = new_layout(client, auth, name="Foreign", blocks=[blk("cover")])
    assert _generate(client, auth, lay, system_id=IDS["B_V1"]).status_code == 422


def test_compare_to_must_be_an_older_version(client, auth):
    lay = new_layout(client, auth, name="Compare", blocks=[blk("cover")])
    assert _generate(client, auth, lay, system_id=IDS["A_V2"], compare_to=IDS["A_V3"]).status_code == 422
    r = _generate(client, auth, lay, system_id=IDS["A_V3"], compare_to=IDS["A_V1"])
    assert r.status_code == 201, r.text
    row = client.get(f"/api/p/alpha/layouts/{lay['id']}/reports", headers=auth("alice")).json()[0]
    assert row["compare_number"] == 1


def test_an_upside_down_period_is_refused(client, auth):
    lay = new_layout(client, auth, name="Upside", blocks=[blk("cover")])
    r = _generate(client, auth, lay, system_id=IDS["A_V2"], period_from="2026-09-12", period_to="2026-09-10")
    assert r.status_code == 422 and "The period ends before it starts." in r.text


def test_references_are_checked_against_the_chosen_version(client, auth):
    lay = new_layout(client, auth, name="Refs", blocks=[blk("control_answers", checklists=["no-such-list"])])
    r = _generate(client, auth, lay, system_id=IDS["A_V2"])
    assert r.status_code == 422 and "invalid_reference" in r.text
