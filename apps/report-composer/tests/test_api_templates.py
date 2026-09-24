"""Templates (report run 2026-09-23: R3.14 to R3.16, R7.3.2, R4.4.5)."""
import pytest

from conftest import IDS, blk, new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def alpha_layout(client, auth):
    return new_layout(client, auth, name="Source", system_id=IDS["A_V2"], blocks=[
        blk("cover", report_title="Alpha review"), blk("test_results", evaluations=[IDS["EVAL_A_V2"]]),
        blk("dashboard_chart", chart_id=33), blk("free_text", text="Alpha secret words")])


# R3.14, R7.3.2
def test_r3_14_saving_as_template_strips_project_data(client, auth):
    lay = alpha_layout(client, auth)
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/template", json={"name": "Standard"}, headers=auth("alice"))
    assert r.status_code == 201
    tid = r.json()["id"]
    listed = client.get("/api/templates", headers=auth("bob")).json()      # R3.16: every signed-in user
    row = next(t for t in listed if t["id"] == tid)
    assert row["block_types"] == ["cover", "test_results", "dashboard_chart", "free_text"]
    # Beta builds from it: no Alpha data arrives (R7.3.2), new instance ids (R3.15)
    b = new_layout(client, auth, slug="beta", who="bob", name="From template", template_id=tid)
    text = repr(b["blocks"])
    for secret in ("Alpha secret words", IDS["EVAL_A_V2"], "'chart_id': 33"):
        assert secret not in text
    assert b["blocks"][0]["options"]["report_title"] == "Alpha review"
    assert b["blocks"][3]["options"]["text"] == "[text]"
    assert not {x["instance_id"] for x in b["blocks"]} & {x["instance_id"] for x in lay["blocks"]}


def test_r3_14_keep_text(client, auth):
    lay = alpha_layout(client, auth)
    tid = client.post(f"/api/p/alpha/layouts/{lay['id']}/template", json={"name": "Kept", "keep_text": True},
                      headers=auth("alice")).json()["id"]
    b = new_layout(client, auth, slug="alpha", name="Kept copy", template_id=tid)
    assert b["blocks"][3]["options"]["text"] == "Alpha secret words"


# R3.15
def test_r3_15_deleting_the_template_leaves_its_layouts(client, auth):
    lay = alpha_layout(client, auth)
    tid = client.post(f"/api/p/alpha/layouts/{lay['id']}/template", json={"name": "Gone"}, headers=auth("alice")).json()["id"]
    copy = new_layout(client, auth, name="Copy", template_id=tid)
    assert client.delete(f"/api/templates/{tid}", headers=auth("alice")).status_code == 204
    assert client.get(f"/api/p/alpha/layouts/{copy['id']}", headers=auth("alice")).status_code == 200


# R3.16, R4.4.5
def test_r3_16_only_the_creator_or_an_admin_deletes(client, auth):
    lay = alpha_layout(client, auth)
    t1 = client.post(f"/api/p/alpha/layouts/{lay['id']}/template", json={"name": "T1"}, headers=auth("alice")).json()["id"]
    t2 = client.post(f"/api/p/alpha/layouts/{lay['id']}/template", json={"name": "T2"}, headers=auth("alice")).json()["id"]
    r = client.delete(f"/api/templates/{t1}", headers=auth("bob"))
    assert r.status_code == 403
    assert client.delete(f"/api/templates/{t1}", headers=auth("alice")).status_code == 204
    assert client.delete(f"/api/templates/{t2}", headers=auth("root-admin", roles=("admin",))).status_code == 204


def test_r4_4_4_a_viewer_cannot_save_a_template(client, auth):
    lay = alpha_layout(client, auth)
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/template", json={"name": "No"}, headers=auth("victor"))
    assert r.status_code == 403
