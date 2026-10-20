"""The five built-in layouts: read-only, listed, opened,
duplicated, exported. Their options are checked against the real renderer in the renderer's
tests/test_builtin_layouts_valid.py."""
import pytest

from v2_fakes import client_v2, fake_v2  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

LEVELS = ["Summary", "Management overview", "Assessment report", "EU AI Act conformity", "Technical dossier"]


def _builtins(client, auth):
    r = client.get("/api/p/alpha/builtin-layouts", headers=auth("victor"))
    assert r.status_code == 200, r.text
    return r.json()


def test_five_levels_in_order(client_v2, auth):
    assert [b["name"] for b in _builtins(client_v2, auth)] == LEVELS
    assert all(b["built_in"] is True and b["id"].startswith("builtin-") for b in _builtins(client_v2, auth))


def test_each_level_holds_more_modules_than_the_one_before(client_v2, auth):
    counts = [len(b["blocks"]) for b in _builtins(client_v2, auth)]
    assert counts == sorted(counts) and len(set(counts)) == 5, counts


def test_the_summary_is_the_four_modules_of_the_spec(client_v2, auth):
    s = _builtins(client_v2, auth)[0]
    assert [b["block_type"] for b in s["blocks"]] == ["cover", "key_figures", "summary_coverage", "changes_since"]
    assert s["blocks"][2]["options"]["show_uncovered_only"] is True
    assert s["show_index"] is False


def test_the_instance_ids_are_stable(client_v2, auth):
    assert [b["instance_id"] for b in _builtins(client_v2, auth)[2]["blocks"]] == \
        [b["instance_id"] for b in _builtins(client_v2, auth)[2]["blocks"]]


def test_no_built_in_holds_a_dashboard_chart_or_a_run_id(client_v2, auth):
    for b in _builtins(client_v2, auth):
        for block in b["blocks"]:
            assert block["block_type"] != "dashboard_chart"
            assert block["options"].get("evaluations", "all") == "all"
            assert block["options"].get("compare_to", "previous") == "previous"


def test_the_technical_dossier_shows_every_tool_run(client_v2, auth):
    runs = [b for b in _builtins(client_v2, auth)[4]["blocks"] if b["block_type"] == "test_runs"]
    assert runs and runs[0]["options"]["detail"] == "full"


def test_one_built_in_is_read_by_its_id(client_v2, auth):
    r = client_v2.get("/api/p/alpha/builtin-layouts/builtin-eu-ai-act", headers=auth("victor"))
    assert r.status_code == 200 and r.json()["name"] == "EU AI Act conformity"
    assert client_v2.get("/api/p/alpha/builtin-layouts/builtin-nope", headers=auth("victor")).status_code == 404


def test_duplicate_makes_an_editable_project_layout(client_v2, auth):
    r = client_v2.post("/api/p/alpha/layouts/builtin-assessment-report/duplicate", json={}, headers=auth("alice"))
    assert r.status_code == 201, r.text
    copy_ = r.json()
    assert copy_["name"] == "Assessment report (copy)" and "built_in" not in copy_
    ids = {b["instance_id"] for b in _builtins(client_v2, auth)[2]["blocks"]}
    assert not ids & {b["instance_id"] for b in copy_["blocks"]}


def test_a_viewer_cannot_duplicate_a_built_in(client_v2, auth):
    r = client_v2.post("/api/p/alpha/layouts/builtin-summary/duplicate", json={}, headers=auth("victor"))
    assert r.status_code == 403


def test_built_ins_cannot_be_changed_or_deleted(client_v2, auth):
    r = client_v2.put("/api/p/alpha/layouts/builtin-summary", json={"name": "x", "revision": 0, "blocks": []},
                      headers=auth("alice"))
    assert r.status_code == 404
    assert client_v2.delete("/api/p/alpha/layouts/builtin-summary", headers=auth("alice")).status_code == 404


def test_a_built_in_exports_as_a_file(client_v2, auth):
    r = client_v2.get("/api/p/alpha/builtin-layouts/builtin-summary/export", headers=auth("victor"))
    assert r.status_code == 200
    doc = r.json()
    assert (doc["format"], doc["version"], doc["name"]) == ("aisc-report-preset", 2, "Summary")
