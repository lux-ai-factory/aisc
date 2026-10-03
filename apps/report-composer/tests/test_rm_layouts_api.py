"""A layout holds no data: the version and the runs are chosen when a report is generated."""
import pytest

from conftest import IDS, blk, new_layout

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]


def test_a_layout_is_created_without_a_version(client, auth):
    r = client.post("/api/p/alpha/layouts", json={"name": "Plain"}, headers=auth("alice"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert "system_id" not in body and body["show_index"] is True and body["blocks"] == []


def test_show_index_and_numbering_are_saved(client, auth):
    lay = new_layout(client, auth, name="Settings", show_index=False, numbering=True)
    got = client.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).json()
    assert (got["show_index"], got["numbering"]) == (False, True)


def test_a_version_sent_by_an_old_client_is_ignored(client, auth):
    lay = new_layout(client, auth, name="Old client", system_id=IDS["A_V2"], toc="off")
    assert "system_id" not in lay and "toc" not in lay and lay["show_index"] is True


def test_a_saved_reference_is_checked_when_generating_not_when_saving(client, auth):
    lay = new_layout(client, auth, name="Refs", blocks=[blk("control_answers", checklists=["no-such-list"])])
    assert lay["blocks"][0]["options"]["checklists"] == ["no-such-list"]


def test_export_is_version_2_without_data(client, auth):
    lay = new_layout(client, auth, name="Exported", blocks=[blk("cover")], show_index=False)
    doc = client.get(f"/api/p/alpha/layouts/{lay['id']}/export", headers=auth("alice")).json()
    assert (doc["format"], doc["version"]) == ("aisc-report-preset", 2)
    assert {"system_id", "language", "toc"}.isdisjoint(doc) and doc["show_index"] is False


def test_an_old_preset_file_imports_with_a_notice_for_each_dropped_option(client, auth):
    old = {"format": "aisc-report-preset", "version": 1, "name": "Old", "toc": "off", "language": "fr",
           "blocks": [{"block_type": "test_results", "options": {"evaluations": [IDS["EVAL_A_V2"]]}}]}
    r = client.post("/api/p/alpha/layouts", json={"file": old}, headers=auth("alice"))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["show_index"] is False and body["name"] == "Old"
    assert body["blocks"][0]["options"].get("evaluations", "all") == "all"     # the run ids are gone
    assert any("Evaluations" in n["message"] for n in body["notices"])


def test_retired_options_are_dropped_or_put_back():
    from report_composer.presets import retire_options
    blocks, changed = retire_options([
        {"block_type": "test_results", "options": {"evaluations": ["x"], "tools": "all"}},
        {"block_type": "changes_since", "options": {"compare_to": "a1000000-0000-4000-8000-000000000001"}},
        {"block_type": "changes_since", "options": {"compare_to": "previous"}}])
    assert blocks[0]["options"] == {"tools": "all"} and blocks[1]["options"]["compare_to"] == "previous"
    assert [(i, o) for i, o, _ in changed] == [(0, "evaluations"), (1, "compare_to")]


def test_a_version_2_file_imports(client, auth):
    doc = {"format": "aisc-report-preset", "version": 2, "name": "New file", "show_index": True, "numbering": True,
           "blocks": [{"block_type": "cover", "options": {}}]}
    r = client.post("/api/p/alpha/layouts", json={"file": doc}, headers=auth("alice"))
    assert r.status_code == 201, r.text and r.json()["numbering"] is True


def test_the_preset_library_routes_are_gone(client, auth):
    assert client.get("/api/presets", headers=auth("alice")).status_code == 404
    lay = new_layout(client, auth, name="No preset")
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/preset", json={"name": "x"}, headers=auth("alice"))
    assert r.status_code in (404, 405)


def test_the_draft_preview_takes_a_version_and_period_not_stored(client, auth, fake_renderer):
    lay = new_layout(client, auth, name="Previewed", blocks=[blk("cover")])
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=auth("alice"),
                    json={"blocks": lay["blocks"], "preview_with": {"system_id": IDS["A_V2"],
                          "period_from": "2026-09-10", "period_to": "2026-09-10", "other_versions": False}})
    assert r.status_code == 200, r.text
    snap = fake_renderer.snapshots[-1]
    assert snap["system_id"] == IDS["A_V2"] and snap["snapshot_version"] == 3
    assert snap["selection"]["period_from"] == "2026-09-10T00:00:00+00:00"
    assert snap["selection"]["period_to"] == "2026-09-11T00:00:00+00:00"
    again = client.get(f"/api/p/alpha/layouts/{lay['id']}", headers=auth("alice")).json()
    assert "preview_with" not in again


def test_the_preview_defaults_to_the_latest_version(client, auth, fake_renderer):
    lay = new_layout(client, auth, name="Latest", blocks=[blk("cover")])
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/preview", headers=auth("alice"), json={"blocks": lay["blocks"]})
    assert r.status_code == 200, r.text
    assert fake_renderer.snapshots[-1]["system_id"] == IDS["A_V3"]


def test_duplicate_keeps_the_settings(client, auth):
    lay = new_layout(client, auth, name="Source", show_index=False, numbering=True)
    r = client.post(f"/api/p/alpha/layouts/{lay['id']}/duplicate", json={}, headers=auth("alice"))
    assert r.status_code == 201, r.text
    assert (r.json()["show_index"], r.json()["numbering"]) == (False, True)
