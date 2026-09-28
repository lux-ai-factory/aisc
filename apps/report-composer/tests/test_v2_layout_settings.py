"""Layout settings of report run v2 (01-specs.md; the language setting is gone in part 2, R2-D1.10 to
R2-D1.12, see test_p2_english_only.py): document settings (R-V5.1 composer
side), the coverage map (R-U2.1, R-U2.5), the optional template (R-U6.1, R-U6.4), the "pick at least one"
rule (R-U4.3), API shapes (R-D.3, R-D.4, R-C.6) and the snapshot (R-S.3, R-V5.14). Report modules
2026-09-28: a layout holds no version, the index is on or off (show_index), and references (the coverage
map's too) are checked against a version when previewing or generating, not when saving. Database tests,
v2 fake renderer.
"""
import pytest

from conftest import IDS, error_code, new_layout, new_template, pdb_of, some_template
from v2_fakes import client_v2, fake_v2, unique, v2blk  # noqa: F401

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

MAP = [{"objective_id": "R1.1", "tests": ["LangBiTe"], "checklists": ["cl-1"]},
       {"objective_id": "R2.1", "tests": [], "checklists": ["cl-2"]}]


def lay(client, auth, **body):
    body.setdefault("name", unique("Layout"))
    body.setdefault("blocks", [v2blk("cover"), v2blk("summary_coverage")])
    return new_layout(client, auth, **body)


def put(client, auth, layout, who="alice", **changes):
    body = {k: layout[k] for k in ("name", "template_id", "revision", "blocks")}
    body.update(changes)
    return client.put(f"/api/p/alpha/layouts/{layout['id']}", json=body, headers=auth(who))


# ── R-C.6, R-D.3 defaults and shapes ─────────────────────────────────────────

def test_r_c_6_new_fields_default_to_todays_behaviour(client_v2, auth):
    lay_ = lay(client_v2, auth)
    got = client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}", headers=auth("victor")).json()
    assert {k: got.get(k) for k in ("show_index", "numbering", "coverage")} == \
        {"show_index": True, "numbering": False, "coverage": []}
    assert "language" not in got and "toc" not in got and "system_id" not in got


def test_r_d_3_post_and_put_accept_the_new_fields(client_v2, auth):
    # R2-D1.10: a language (and since report modules, a toc) key is accepted and ignored
    lay_ = lay(client_v2, auth, language="fr", toc="on", show_index=False, numbering=True, coverage=MAP[:1])
    assert (lay_.get("show_index"), lay_.get("numbering"), lay_.get("coverage")) == (False, True, MAP[:1])
    assert "language" not in lay_ and "toc" not in lay_
    r = put(client_v2, auth, lay_, language="de", show_index=True, numbering=False, coverage=MAP)
    assert r.status_code == 200, r.text[:300]
    assert (r.json().get("show_index"), r.json().get("numbering"), r.json().get("coverage")) == (True, False, MAP)
    assert "language" not in r.json()


def test_r_d_3_absent_on_put_keeps_the_current_value(client_v2, auth):
    lay_ = lay(client_v2, auth)
    first = put(client_v2, auth, lay_, show_index=False, numbering=True, coverage=MAP)
    assert first.status_code == 200, first.text[:300]
    second = put(client_v2, auth, first.json())       # an older client sends none of them
    assert second.status_code == 200
    assert (second.json().get("show_index"), second.json().get("numbering"), second.json().get("coverage")) == \
        (False, True, MAP)


# ── R-D.4 validation of the new fields ───────────────────────────────────────

@pytest.mark.parametrize("change,code", [
    ({"show_index": "sometimes"}, "invalid_request"),
    ({"numbering": "yes"}, "invalid_request"),
])
def test_r_d_4_bad_settings_are_refused(client_v2, auth, change, code):
    lay_ = lay(client_v2, auth)
    r = put(client_v2, auth, lay_, **change)
    assert r.status_code == 422 and error_code(r) == code


# ── R-U2.1, R-U2.5 the coverage map ──────────────────────────────────────────

def test_r_u2_1_the_map_is_saved_and_returned(client_v2, auth):
    lay_ = lay(client_v2, auth)
    r = put(client_v2, auth, lay_, coverage=MAP)
    assert r.status_code == 200, r.text[:300]
    assert client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}", headers=auth("alice")).json().get("coverage") == MAP


@pytest.mark.parametrize("coverage", [
    [MAP[0], MAP[0]],                                                        # duplicate objective_id
    [{"objective_id": f"R{i}", "tests": [], "checklists": []} for i in range(201)],   # over 200
    {"objective_id": "R1.1"},                                                # not a list
])
def test_r_u2_1_map_shape_is_checked(client_v2, auth, coverage):
    lay_ = lay(client_v2, auth)
    r = put(client_v2, auth, lay_, coverage=coverage)
    assert r.status_code == 422


@pytest.mark.parametrize("bad,pointer", [
    ([{"objective_id": "R9.9", "tests": [], "checklists": ["cl-1"]}], "/coverage/0/objective_id"),
    ([{"objective_id": "R1.1", "tests": ["LangBiTe", "Nope"], "checklists": []}], "/coverage/0/tests/1"),
    ([{"objective_id": "R1.1", "tests": [], "checklists": ["cl-9"]}], "/coverage/0/checklists/0"),
])
def test_r_u2_5_map_values_must_be_choices_of_the_chosen_version(client_v2, auth, bad, pointer):
    lay_ = lay(client_v2, auth)
    assert put(client_v2, auth, lay_, coverage=bad).status_code == 200      # saved: checked with a version
    r = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/reports", json={"system_id": IDS["A_V2"]},
                       headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "invalid_reference"
    detail = next(d for d in r.json()["error"]["details"] if d.get("pointer") == pointer)
    assert detail.get("instance_id") is None


# ── R-U4.3 "Only these" with nothing ticked ──────────────────────────────────

def test_r_u4_3_an_empty_list_is_refused_with_pick_at_least_one(client_v2, auth):
    lay_ = lay(client_v2, auth)
    tests = v2blk("test_results", tools=[])
    r = put(client_v2, auth, lay_, blocks=[tests])
    assert r.status_code == 422 and error_code(r) == "invalid_options"
    d = next(d for d in r.json()["error"]["details"] if d.get("pointer") == "/tools")
    assert d["message"] == "Pick at least one, or choose All." and d["instance_id"] == tests["instance_id"]


# ── R-U6.1, R-U6.4 no project template needed ────────────────────────────────

def test_r_u6_1_a_layout_is_saved_and_generated_without_a_template(client_v2, auth, fake_v2):
    r = client_v2.post("/api/p/alpha/layouts", json={"name": "Plain look",
                                                    "template_id": None, "blocks": [v2blk("cover")]},
                       headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    assert r.json()["template_id"] is None
    g = client_v2.post(f"/api/p/alpha/layouts/{r.json()['id']}/reports", json={"system_id": IDS["A_V2"]},
                       headers=auth("alice"))
    assert g.status_code == 201, g.text[:300]
    assert "style" not in fake_v2.snapshots[-1]


def test_r_u6_1_template_of_another_project_still_refused(client_v2, auth):
    gamma_t = new_template(client_v2, auth, slug="gamma", name=unique("Gamma look"))
    r = client_v2.post("/api/p/alpha/layouts", json={"name": "Wrong",
                                                    "template_id": gamma_t["id"]}, headers=auth("alice"))
    assert r.status_code == 422 and error_code(r) == "template_not_in_project"


def test_r_u6_4_a_deleted_template_leaves_a_layout_that_saves_and_generates(client_v2, auth, fake_v2):
    t = new_template(client_v2, auth, name=unique("Going"))
    lay_ = lay(client_v2, auth, template_id=t["id"])
    assert client_v2.delete(f"/api/p/alpha/templates/{t['id']}", headers=auth("alice")).status_code == 204
    fresh = client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}", headers=auth("alice")).json()
    assert put(client_v2, auth, fresh).status_code == 200
    g = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/reports", json={"system_id": IDS["A_V2"]},
                       headers=auth("alice"))
    assert g.status_code == 201, g.text[:300]
    assert "style" not in fake_v2.snapshots[-1]


# ── R-S.3, R-V5.14, R-U2.1: the v2 snapshot (no language, R2-D1.12) ───────────

def test_r_s_3_the_stored_snapshot_is_version_3_with_the_new_keys(client_v2, auth, fake_v2, bed):
    lay_ = lay(client_v2, auth, show_index=True, numbering=True, coverage=MAP)
    r = client_v2.post(f"/api/p/alpha/layouts/{lay_['id']}/reports", json={"system_id": IDS["A_V2"]},
                       headers=auth("alice"))
    assert r.status_code == 201, r.text[:300]
    rid = r.json()["id"]
    sent = fake_v2.snapshots[-1]
    assert sent.get("snapshot_version") == 3 and "language" not in sent and "selection" in sent
    assert sent.get("document") == {"id": rid, "toc": "on", "numbering": True}
    assert sent.get("coverage_links") == MAP
    import json

    stored = json.loads(bed.scalar(pdb_of("A"), f"SELECT snapshot::text FROM report_composer.generated_report WHERE id = '{rid}'"))
    for key in ("snapshot_version", "document", "coverage_links", "selection"):
        assert stored.get(key) == sent[key], key
    assert "language" not in stored


def test_r_u2_1_coverage_links_are_always_in_new_snapshots(client_v2, auth, fake_v2):
    lay_ = lay(client_v2, auth)
    client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}/preview", headers=auth("victor"))
    assert fake_v2.snapshots[-1].get("coverage_links", "absent") == []


def test_r_v5_14_the_preview_has_no_document_id(client_v2, auth, fake_v2):
    lay_ = lay(client_v2, auth)
    client_v2.get(f"/api/p/alpha/layouts/{lay_['id']}/preview", headers=auth("victor"))
    doc = fake_v2.snapshots[-1].get("document")
    assert doc is not None and doc.get("id") is None and fake_v2.snapshots[-1]["mode"] == "preview"
