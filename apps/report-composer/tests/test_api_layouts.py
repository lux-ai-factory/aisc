"""Layouts through the API (report run 2026-09-23: R3.1 to R3.13, R4.3, R4.3.1, R4.3.2, R4.1.3, D11,
D13, R7.3.1). Database tests on the bed, with a fake renderer."""
import pytest

from conftest import DEFAULT_ORDER, IDS, blk, error_code, new_layout, put_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


# R4.1.3, D13
def test_r4_1_3_migrations_run_at_start(client, bed):
    client.get("/api/block-types")
    assert bed.scalar("platform", "SELECT count(*) FROM report_composer.schema_migration") not in ("", "0")
    owner = bed.scalar("platform", "SELECT nspowner::regrole FROM pg_namespace WHERE nspname = 'report_composer'")
    assert owner == "report_composer_rw"


# R4.3 systems
def test_r4_3_systems_newest_first(client, auth):
    r = client.get("/api/p/alpha/systems", headers=auth("victor"))
    assert r.status_code == 200
    assert [s["number"] for s in r.json()] == [3, 2, 1]
    assert r.json()[0] == {"pid": IDS["A_V3"], "number": 3, "name": "Alpha scorer", "release": "1.1"}


def test_r4_3_block_types_come_from_the_renderer(client, auth):
    r = client.get("/api/block-types", headers=auth("bob"))
    assert r.status_code == 200 and "free_text" in [t["type_id"] for t in r.json()]


def test_r4_3_choices_come_from_the_renderer_for_the_project(client, auth, fake_renderer):
    r = client.get(f"/api/p/alpha/choices?block_type=test_results&system_id={IDS['A_V2']}", headers=auth("victor"))
    assert r.status_code == 200 and IDS["EVAL_A_V2"] in [c["value"] for c in r.json()["evaluations"]]
    assert fake_renderer.choice_calls[-1] == (IDS["A"], IDS["A_V2"], "test_results")


def test_r7_3_1_choices_for_a_version_of_another_project_are_refused(client, auth, fake_renderer):
    r = client.get(f"/api/p/alpha/choices?block_type=test_results&system_id={IDS['B_V1']}", headers=auth("alice"))
    assert r.status_code in (404, 422)
    assert all(c[1] != IDS["B_V1"] for c in fake_renderer.choice_calls)


# R3.3, R3.4
def test_r3_3_a_new_layout_gets_the_default_blocks_and_the_latest_version(client, auth):
    lay = new_layout(client, auth, name="Default one")
    assert [b["block_type"] for b in lay["blocks"]] == DEFAULT_ORDER
    assert lay["system_id"] == IDS["A_V3"]
    assert lay["revision"] == 1


def test_r4_3_get_layout_shape(client, auth):
    lay = new_layout(client, auth, name="Shape", system_id=IDS["A_V2"], blocks=[blk("free_text", text="x")])
    r = client.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("victor"))
    assert r.status_code == 200
    body = r.json()
    assert set(body) >= {"id", "name", "description", "system_id", "revision", "blocks"}
    assert body["blocks"][0]["block_type"] == "free_text" and body["blocks"][0]["options"]["text"] == "x"


# R3.1
def test_r3_1_the_version_must_belong_to_the_project(client, auth):
    r = client.post("/api/p/alpha/layouts", json={"name": "x", "system_id": IDS["B_V1"]}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "system_not_in_project"


def test_r3_1_names_are_unique_per_project(client, auth):
    new_layout(client, auth, name="Same name")
    r = client.post("/api/p/alpha/layouts", json={"name": "Same name"}, headers=auth("alice"))
    assert r.status_code in (409, 422)
    new_layout(client, auth, slug="gamma", name="Same name")      # another project may


# R3.2
def test_r3_2_a_layout_never_moves_between_projects(client, auth):
    lay = new_layout(client, auth)
    r = put_layout(client, auth, lay, project_id=IDS["B"])
    assert r.status_code == 422 and error_code(r) == "immutable_field"


# R3.11, R4.2.3: Save sends the full ordered list
def test_r3_11_saving_bumps_the_revision_and_keeps_the_order(client, auth):
    lay = new_layout(client, auth, system_id=IDS["A_V2"])
    order = [blk("free_text", text="z"), blk("cover"), blk("ai_card")]
    r = put_layout(client, auth, lay, blocks=order)
    assert r.status_code == 200 and r.json()["revision"] == 2
    got = client.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).json()
    assert [b["instance_id"] for b in got["blocks"]] == [b["instance_id"] for b in order]


def test_r3_11_a_stale_revision_is_409(client, auth):
    lay = new_layout(client, auth)
    assert put_layout(client, auth, lay).status_code == 200
    r = put_layout(client, auth, lay)                 # still based on revision 1
    assert r.status_code == 409 and error_code(r) == "stale_revision"
    assert "2" in r.text


# R3.5, R4.3.1
def test_r3_5_unknown_block_type_and_invalid_options(client, auth):
    lay = new_layout(client, auth, system_id=IDS["A_V2"])
    r = put_layout(client, auth, lay, blocks=[blk("nope")])
    assert r.status_code == 422 and error_code(r) == "unknown_block_type"
    bad = blk("dashboard_chart", chart_id=33, width=5)
    r = put_layout(client, auth, lay, blocks=[bad])
    assert r.status_code == 422 and error_code(r) == "invalid_options"
    detail = r.json()["error"]["details"][0]
    assert detail["instance_id"] == bad["instance_id"] and detail["pointer"] == "/width"
    assert set(r.json()["error"]) == {"code", "message", "details"}


# R3.6, R7.3.1
def test_r3_6_a_reference_of_another_project_is_refused(client, auth):
    lay = new_layout(client, auth, system_id=IDS["A_V2"])
    r = put_layout(client, auth, lay, blocks=[blk("test_results", evaluations=[IDS["EVAL_B_V1"]])])
    assert r.status_code == 422 and error_code(r) == "invalid_reference"


# R3.7
def test_r3_7_limits(client, auth):
    lay = new_layout(client, auth, system_id=IDS["A_V2"])
    r = put_layout(client, auth, lay, blocks=[blk("free_text", text="x") for _ in range(51)])
    assert error_code(r) == "too_many_blocks"
    r = put_layout(client, auth, lay, blocks=[blk("dashboard_chart", chart_id=33) for _ in range(11)])
    assert error_code(r) == "too_many_blocks"
    r = put_layout(client, auth, lay, blocks=[blk("cover"), blk("cover")])
    assert error_code(r) == "duplicate_cover"


# R3.8
def test_r3_8_zero_blocks_saves(client, auth):
    lay = new_layout(client, auth)
    assert put_layout(client, auth, lay, blocks=[]).status_code == 200


# R3.9
def test_r3_9_changing_the_version_checks_references(client, auth):
    lay = new_layout(client, auth, system_id=IDS["A_V2"], blocks=[blk("test_results", evaluations=[IDS["EVAL_A_V2"]])])
    r = put_layout(client, auth, lay, system_id=IDS["A_V3"])
    assert r.status_code == 422 and error_code(r) == "invalid_reference"
    r = put_layout(client, auth, lay, system_id=IDS["A_V3"], reset_invalid=True)
    assert r.status_code == 200
    assert r.json()["blocks"][0]["options"]["evaluations"] == "all" and r.json()["system_id"] == IDS["A_V3"]


# R3.10
def test_r3_10_a_block_type_that_went_away(client, auth, bed):
    lay = new_layout(client, auth, system_id=IDS["A_V2"], blocks=[blk("free_text", text="x")])
    bed.psql("platform", f"UPDATE report_composer.layout_block SET block_type = 'gone_type' "
                         f"WHERE layout_id = '{lay['id']}'")
    r = client.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice"))
    assert r.status_code == 200 and r.json()["blocks"][0]["block_type"] == "gone_type"
    page = client.get(f"/p/alpha/layouts/{lay['id']}", headers=auth("alice"))
    assert "unknown type" in page.text.lower()
    assert client.get(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=auth("alice")).status_code == 200
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "unknown_block_type"


# validate endpoint
def test_r4_3_validate(client, auth):
    lay = new_layout(client, auth, system_id=IDS["A_V2"], blocks=[blk("free_text", text="x")])
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/validate", headers=auth("victor"))
    assert r.status_code == 200 and r.json() == {"valid": True, "problems": []}


# R4.3 list, R4.2.1
def test_r4_3_list_fields(client, auth):
    new_layout(client, auth, name="Listed", system_id=IDS["A_V2"])
    rows = client.get("/api/p/alpha/layouts", headers=auth("victor")).json()
    row = next(r for r in rows if r["name"] == "Listed")
    assert row["system_number"] == 2 and row["revision"] == 1
    assert "updated_at" in row and "last_report" in row


# R3.13
def test_r3_13_deleting_a_layout_deletes_its_reports(client, auth, bed):
    lay = new_layout(client, auth, system_id=IDS["A_V2"], blocks=[blk("free_text", text="x")])
    assert client.post(f"/api/p/alpha/layouts/{lay['id']}/reports", json={}, headers=auth("alice")).status_code == 201
    assert client.delete(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).status_code == 204
    assert bed.scalar("platform", f"SELECT count(*) FROM report_composer.generated_report WHERE layout_id = '{lay['id']}'") == "0"
    assert client.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).status_code == 404


# R4.3.2, R7.3.1
def test_r4_3_2_a_layout_of_another_project_is_404(client, auth, bed):
    lay = new_layout(client, auth, slug="alpha")
    bed.psql("platform", "INSERT INTO core.project_member (project_id, subject, role) VALUES "
                         f"('{IDS['B']}', 'alice', 'editor') ON CONFLICT DO NOTHING")
    try:
        for method in ("get", "delete"):
            r = getattr(client, method)(f"/api/p/beta/layouts/{lay['id']}", headers=auth("alice"))
            assert r.status_code == 404 and error_code(r) == "not_found"
        r = put_layout(client, auth, lay, slug="beta")
        assert r.status_code == 404
    finally:
        bed.psql("platform", f"DELETE FROM core.project_member WHERE project_id = '{IDS['B']}' AND subject = 'alice'")


# D11
def test_d11_the_project_may_be_named_by_pid(client, auth):
    assert client.get(f"/api/p/{IDS['A']}/layouts", headers=auth("victor")).status_code == 200
    r = client.get(f"/p/{IDS['A']}/", headers=auth("victor"), follow_redirects=False)
    assert r.status_code in (302, 303, 307) and r.headers["location"].rstrip("/").endswith("/p/alpha")
