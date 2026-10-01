"""Collect evidence (evidence links plan 2026-09-30, step B): which tests and controls give
evidence for which selected control objective, many to many, per project (D3).

The links live in the project's own database (schema `evidence`, template 0016), written only by
the platform. What can be linked is read, as report_ro (D4), from the other steps' tables in the
same database: the objectives selected in step 2 (control_objectives.objective_selection, of the
latest card version that has one), the installed plugins (engine.aisc_backend_plugin) and the
installed checklists (controls.checklist). Those tables belong to their modules; here they are
stood in for with the columns this reads, granted to report_ro as the modules grant them.

Stale (D7): a link whose objective is no longer selected, whose plugin is disabled or removed, or
whose checklist is gone is kept and shown with its reason; no new link may be made to it.
"""
from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import evidence, projectdb
from tests.conftest import needs_database
from tests.connection_support import Stub

pytestmark = needs_database
ALICE = "00000000-0000-0000-0000-00000000a11c"   # owner
BOB = "00000000-0000-0000-0000-000000000b0b"     # editor
VERA = "00000000-0000-0000-0000-00000000fe1a"    # viewer

READER = os.environ.get("EVIDENCE_TEST_READER_URL")

MODULE_TABLES = """
CREATE TABLE IF NOT EXISTS control_objectives.project (id varchar(32) PRIMARY KEY, system_id uuid NOT NULL);
CREATE TABLE IF NOT EXISTS control_objectives.objective_selection (
    project_id varchar(32) PRIMARY KEY, objective_ids text[] NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS engine.aisc_backend_plugin (
    id serial PRIMARY KEY, package_name text NOT NULL, version text NOT NULL, display_name text NOT NULL,
    catalogue_slug text, enabled boolean NOT NULL DEFAULT true);
CREATE TABLE IF NOT EXISTS controls.checklist (id text PRIMARY KEY, "catalogueId" text, title text NOT NULL);
CREATE TABLE IF NOT EXISTS control_objectives.objective_set_version (
    id varchar(32) PRIMARY KEY, set_id varchar(32) NOT NULL, number int NOT NULL);
CREATE TABLE IF NOT EXISTS control_objectives.objective_set_version_item (
    set_version_id varchar(32) NOT NULL, objective_id text NOT NULL, label text NOT NULL, dimension text NOT NULL,
    PRIMARY KEY (set_version_id, objective_id));
GRANT SELECT ON control_objectives.project, control_objectives.objective_selection,
    control_objectives.objective_set_version, control_objectives.objective_set_version_item,
    engine.aisc_backend_plugin, controls.checklist TO report_ro;
"""


@pytest.fixture(autouse=True)
def _reader(monkeypatch):
    if not READER:
        pytest.skip("EVIDENCE_TEST_READER_URL (report_ro on the throwaway, with {database}) is not set")
    monkeypatch.setenv("EVIDENCE_READER_DATABASE_URL", READER)


@pytest.fixture(autouse=True)
def catalogue(monkeypatch):
    """The control-objectives service's public catalogue, which names the objectives."""
    stub = Stub()
    stub.route("GET", "/api/control-objectives", (200, [
        {"id": "O1", "sub_requirement_label": "Risk management system", "macro_id": "R1"},
        {"id": "O7", "sub_requirement_label": "Security incidents", "macro_id": "R2"},
        {"id": "O9", "sub_requirement_label": "Calibration", "macro_id": "R2"},
        {"id": "O10", "sub_requirement_label": "Safe state", "macro_id": "R2"},
        {"id": "O24", "sub_requirement_label": "Human oversight", "macro_id": "R6"}]))
    monkeypatch.setenv("CONTROL_OBJECTIVES_URL", stub.base)
    evidence.forget_titles()
    yield stub
    stub.stop()
    evidence.forget_titles()


def sql(dsn, pid, statement, params=()):
    with psycopg.connect(make_conninfo(dsn, dbname=projectdb.database_name(pid))) as conn:
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else None


@pytest.fixture
def project(client, as_user, unique, dsn):
    """A project with Bob as editor and Vera as viewer, whose steps 2 and 3 have made their choices:
    v1 selected O1 and O7, v2 (the latest) selects O1 and O24; LangBiTe and Promptfoo are
    installed (Promptfoo disabled); one checklist is installed."""
    made = client.post("/projects", json={"name": unique("evd")}, headers=as_user(ALICE))
    assert made.status_code == 201, made.text
    p = made.json()
    for subject, role in ((BOB, "editor"), (VERA, "viewer")):
        r = client.post(f"/projects/{p['slug']}/members", json={"subject": subject, "role": role},
                        headers=as_user(ALICE))
        assert r.status_code in (200, 201), r.text
    pid = p["pid"]
    sql(dsn, pid, MODULE_TABLES)
    v1, v2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
    sql(dsn, pid, "INSERT INTO project.system (pid, number, name) VALUES (%s, 1, 'S'), (%s, 2, 'S')", (v1, v2))
    sql(dsn, pid, "INSERT INTO control_objectives.project VALUES ('a1', %s), ('a2', %s)", (v1, v2))
    sql(dsn, pid, "INSERT INTO control_objectives.objective_selection (project_id, objective_ids) VALUES"
                  " ('a1', '{O1,O7}'), ('a2', '{O1,O24}')")
    sql(dsn, pid, "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name, enabled) VALUES"
                  " ('aisc-plugin-langbite', '1.0', 'LangBiTe', true),"
                  " ('aisc-plugin-promptfoo', '1.0', 'Promptfoo', false)")
    sql(dsn, pid, "INSERT INTO controls.checklist (id, \"catalogueId\", title) VALUES ('ck1', 'gov', 'Governance')")
    return p


def get(client, as_user, project, who=ALICE):
    return client.get(f"/projects/{project['slug']}/evidence", headers=as_user(who))


def put(client, as_user, project, links, who=ALICE):
    return client.put(f"/projects/{project['slug']}/evidence/links", json={"links": links},
                      headers=as_user(who))


LB = {"objective_id": "O1", "kind": "test", "key": "aisc-plugin-langbite"}
GOV = {"objective_id": "O24", "kind": "control", "key": "ck1"}


# ── the table ───────────────────────────────────────────────────────────────

def test_the_evidence_schema_is_made_and_the_readers_read_it(project, dsn):
    cols = sql(dsn, project["pid"], "SELECT column_name FROM information_schema.columns"
                                    " WHERE table_schema = 'evidence' AND table_name = 'link' ORDER BY ordinal_position")
    assert [c[0] for c in cols] == ["objective_id", "kind", "item_key", "created_by", "created_at"]
    rows = sql(dsn, project["pid"], "SELECT r, has_table_privilege(r, 'evidence.link', 'SELECT'),"
                                    " has_table_privilege(r, 'evidence.link', 'INSERT')"
                                    " FROM unnest(array['report_ro', 'dashboard_ro', 'report_composer_rw']) r"
                                    " WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r)")
    assert rows and all(sel and not ins for _, sel, ins in rows)
    # the composer copies the links into a report's snapshot when it issues one (D5)
    assert "report_composer_rw" in {r for r, _, _ in rows}


def test_a_link_is_one_objective_one_item(project, dsn):
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, project["pid"], "INSERT INTO evidence.link (objective_id, kind, item_key, created_by)"
                                 " VALUES ('O1', 'model', 'x', 'a')")


# ── what the page lists ─────────────────────────────────────────────────────

def test_the_page_lists_the_latest_selection_the_plugins_and_the_checklists(client, as_user, project):
    body = get(client, as_user, project).json()
    assert [(o["id"], o["stale"]) for o in body["objectives"]] == [("O1", None), ("O24", None)]
    assert [(t["key"], t["label"], t["stale"]) for t in body["tests"]] == [
        ("aisc-plugin-langbite", "LangBiTe", None), ("aisc-plugin-promptfoo", "Promptfoo", "disabled")]
    assert [(c["key"], c["label"], c["stale"]) for c in body["controls"]] == [("ck1", "Governance", None)]
    assert body["links"] == [] and body["can_edit"] is True


def test_a_project_whose_steps_have_nothing_yet_lists_nothing(client, as_user, unique):
    made = client.post("/projects", json={"name": unique("evd")}, headers=as_user(ALICE)).json()
    body = client.get(f"/projects/{made['slug']}/evidence", headers=as_user(ALICE)).json()
    assert (body["objectives"], body["tests"], body["controls"], body["links"]) == ([], [], [], [])


def test_a_viewer_reads_and_may_not_edit(client, as_user, project):
    body = get(client, as_user, project, VERA)
    assert body.status_code == 200 and body.json()["can_edit"] is False
    assert put(client, as_user, project, [LB], VERA).status_code == 403


def test_a_stranger_gets_404(client, as_user, project):
    stranger = "00000000-0000-0000-0000-0000000057a4"
    assert get(client, as_user, project, stranger).status_code == 404
    assert put(client, as_user, project, [LB], stranger).status_code == 404


def test_the_objectives_are_named_from_the_catalogue(client, as_user, project):
    body = get(client, as_user, project).json()
    assert [(o["id"], o["title"]) for o in body["objectives"]] == [
        ("O1", "Risk management system"), ("O24", "Human oversight")]


def test_a_catalogue_that_is_down_leaves_the_names_empty(client, as_user, project, catalogue, monkeypatch):
    monkeypatch.setenv("CONTROL_OBJECTIVES_URL", "http://127.0.0.1:9")
    evidence.forget_titles()
    body = get(client, as_user, project)
    assert body.status_code == 200 and [o["title"] for o in body.json()["objectives"]] == ["", ""]


# ── linking (many to many) ──────────────────────────────────────────────────

def test_an_editor_links_tests_and_controls_to_objectives(client, as_user, project, dsn):
    both = {"objective_id": "O24", "kind": "test", "key": "aisc-plugin-langbite"}
    r = put(client, as_user, project, [LB, GOV, both], BOB)
    assert r.status_code == 200, r.text
    assert sorted((l["objective_id"], l["kind"], l["key"]) for l in r.json()["links"]) == [
        ("O1", "test", "aisc-plugin-langbite"), ("O24", "control", "ck1"), ("O24", "test", "aisc-plugin-langbite")]
    assert sql(dsn, project["pid"], "SELECT count(*) FROM evidence.link") == [(3,)]
    assert sql(dsn, project["pid"], "SELECT DISTINCT created_by FROM evidence.link") == [(BOB,)]


def test_saving_replaces_the_links_and_keeps_who_made_the_old_ones(client, as_user, project, dsn):
    put(client, as_user, project, [LB, GOV], BOB)
    r = put(client, as_user, project, [LB], ALICE)
    assert [(l["objective_id"], l["key"]) for l in r.json()["links"]] == [("O1", "aisc-plugin-langbite")]
    assert sql(dsn, project["pid"], "SELECT created_by FROM evidence.link") == [(BOB,)]


@pytest.mark.parametrize("link, why", [
    ({"objective_id": "O7", "kind": "test", "key": "aisc-plugin-langbite"}, "O7 is not selected"),
    ({"objective_id": "O1", "kind": "test", "key": "aisc-plugin-promptfoo"}, "disabled"),
    ({"objective_id": "O1", "kind": "test", "key": "aisc-plugin-nothing"}, "not installed"),
    ({"objective_id": "O1", "kind": "control", "key": "ck9"}, "not installed"),
    ({"objective_id": "O1", "kind": "model", "key": "ck1"}, "kind"),
])
def test_a_new_link_to_something_not_there_is_refused(client, as_user, project, link, why, dsn):
    r = put(client, as_user, project, [LB, link])
    assert r.status_code == 422 and why in r.text, r.text
    assert sql(dsn, project["pid"], "SELECT count(*) FROM evidence.link") == [(0,)]


# ── stale (D7) ──────────────────────────────────────────────────────────────

def test_links_that_went_stale_are_kept_and_shown_with_their_reason(client, as_user, project, dsn):
    promptfoo_on_r6 = {"objective_id": "O24", "kind": "test", "key": "aisc-plugin-promptfoo"}
    sql(dsn, project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = true")
    put(client, as_user, project, [LB, GOV, promptfoo_on_r6])
    # step 2 unselects O24, the engine disables Promptfoo, the checklist is deleted
    sql(dsn, project["pid"], "UPDATE control_objectives.objective_selection SET objective_ids = '{O1}'"
                             " WHERE project_id = 'a2'")
    sql(dsn, project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = false"
                             " WHERE package_name = 'aisc-plugin-promptfoo'")
    sql(dsn, project["pid"], "DELETE FROM controls.checklist")
    body = get(client, as_user, project).json()
    assert [(o["id"], o["stale"]) for o in body["objectives"]] == [("O1", None), ("O24", "not selected")]
    assert [(c["key"], c["label"], c["stale"]) for c in body["controls"]] == [("ck1", "ck1", "deleted")]
    stale = {(l["objective_id"], l["key"]): l["stale"] for l in body["links"]}
    assert stale == {("O1", "aisc-plugin-langbite"): None, ("O24", "ck1"): "not selected",
                     ("O24", "aisc-plugin-promptfoo"): "not selected"}
    # saving the page as it is keeps the stale links
    r = put(client, as_user, project, [{k: l[k] for k in ("objective_id", "kind", "key")} for l in body["links"]])
    assert r.status_code == 200, r.text
    assert sql(dsn, project["pid"], "SELECT count(*) FROM evidence.link") == [(3,)]


def test_a_removed_plugin_is_listed_as_removed_while_a_link_names_it(client, as_user, project, dsn):
    put(client, as_user, project, [LB])
    sql(dsn, project["pid"], "DELETE FROM engine.aisc_backend_plugin WHERE package_name = 'aisc-plugin-langbite'")
    body = get(client, as_user, project).json()
    assert ("aisc-plugin-langbite", "removed") in [(t["key"], t["stale"]) for t in body["tests"]]
    assert body["links"][0]["stale"] == "removed"


# ── trustworthiness dimensions (2026-10-01) ─────────────────────────────────
# Each objective belongs to the dimension of its macro-requirement (O7 -> R2). Each test and
# control takes its dimensions from its tags in the tools catalogue; a sub-dimension tag counts as
# its parent dimension. A link may only join an objective and an item of the same dimension.

def dim(slug):
    return {"slug": slug, "section": "dimension", "parent_dimension_slug": None}


def subdim(slug, parent):
    return {"slug": slug, "section": "testing_subdim", "parent_dimension_slug": parent}


TOOLS = [
    # in R1 directly and in R6 directly
    {"slug": "langbite", "package_name": "aisc-plugin-langbite",
     "tags": [{"slug": "test", "section": "type", "parent_dimension_slug": None},
              dim("human-agency-oversight"), dim("societal-environmental-wellbeing")]},
    # in R6 only through a sub-dimension
    {"slug": "promptfoo", "package_name": "aisc-plugin-promptfoo",
     "tags": [subdim("energy-use", "societal-environmental-wellbeing")]},
    # the checklist's catalogue entry, in R6
    {"slug": "gov", "package_name": None, "tags": [dim("societal-environmental-wellbeing")]},
    {"slug": "untagged", "package_name": "aisc-plugin-untagged", "tags": []},
]


@pytest.fixture(autouse=True)
def tools(monkeypatch):
    """The tools catalogue (the catalogue's API), which tags tests and controls with dimensions."""
    stub = Stub()
    stub.route("GET", "/tool/", (200, TOOLS))
    monkeypatch.setenv("CATALOGUE_URL", stub.base)
    evidence.forget_dimensions()
    yield stub
    stub.stop()
    evidence.forget_dimensions()


def test_the_page_lists_the_eleven_dimensions_in_order(client, as_user, project):
    body = get(client, as_user, project).json()
    assert [d["id"] for d in body["dimensions"]] == [f"R{n}" for n in range(1, 12)]
    assert body["dimensions"][0]["title"] == "Human Agency and Oversight"
    assert body["dimensions"][4]["title"] == "Diversity, Non-Discrimination and Fairness"
    assert body["dimensions_known"] is True


def test_an_objective_is_in_the_dimension_of_its_requirement(client, as_user, project):
    body = get(client, as_user, project).json()
    assert [(o["id"], o["dimension"]) for o in body["objectives"]] == [("O1", "R1"), ("O24", "R6")]


def test_tests_and_controls_take_their_dimensions_from_the_catalogue(client, as_user, project, tools):
    body = get(client, as_user, project).json()
    # LangBiTe has no catalogue slug stored here: it is found by its package name
    assert {t["key"]: t["dimensions"] for t in body["tests"]} == {
        "aisc-plugin-langbite": ["R1", "R6"], "aisc-plugin-promptfoo": ["R6"]}
    # the checklist is found by its catalogue id
    assert {c["key"]: c["dimensions"] for c in body["controls"]} == {"ck1": ["R6"]}
    assert tools.requests("GET", "/tool/")[0]["path"] == "/tool/?detailed=true"


def test_a_stored_catalogue_slug_wins_over_the_package_name(client, as_user, project, dsn):
    sql(dsn, project["pid"], "UPDATE engine.aisc_backend_plugin SET catalogue_slug = 'gov'"
                             " WHERE package_name = 'aisc-plugin-langbite'")
    body = get(client, as_user, project).json()
    assert {t["key"]: t["dimensions"] for t in body["tests"]}["aisc-plugin-langbite"] == ["R6"]


def test_an_item_with_no_dimension_in_the_catalogue_has_none(client, as_user, project, dsn):
    sql(dsn, project["pid"], "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name)"
                             " VALUES ('aisc-plugin-untagged', '1.0', 'Untagged'), ('aisc-plugin-local', '1.0', 'Local')")
    body = get(client, as_user, project).json()
    found = {t["key"]: t["dimensions"] for t in body["tests"]}
    assert found["aisc-plugin-untagged"] == [] and found["aisc-plugin-local"] == []


def test_a_link_across_dimensions_is_refused(client, as_user, project, dsn):
    sql(dsn, project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = true")
    r = put(client, as_user, project, [LB, {"objective_id": "O1", "kind": "control", "key": "ck1"}])
    assert r.status_code == 422 and "control ck1 is not in R1 Human Agency and Oversight" in r.text, r.text
    r = put(client, as_user, project, [{"objective_id": "O1", "kind": "test", "key": "aisc-plugin-promptfoo"}])
    assert r.status_code == 422 and "not in R1" in r.text, r.text
    assert sql(dsn, project["pid"], "SELECT count(*) FROM evidence.link") == [(0,)]


def test_a_link_within_a_dimension_reached_through_a_sub_dimension_is_kept(client, as_user, project, dsn):
    sql(dsn, project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = true")
    r = put(client, as_user, project, [{"objective_id": "O24", "kind": "test", "key": "aisc-plugin-promptfoo"}])
    assert r.status_code == 200, r.text


def test_a_catalogue_that_is_down_leaves_the_dimensions_unknown_and_refuses_nothing_for_them(
        client, as_user, project, monkeypatch):
    monkeypatch.setenv("CATALOGUE_URL", "http://127.0.0.1:9")
    evidence.forget_dimensions()
    body = get(client, as_user, project).json()
    assert body["dimensions_known"] is False
    assert {t["dimensions"] for t in body["tests"]} == {None}
    r = put(client, as_user, project, [{"objective_id": "O1", "kind": "control", "key": "ck1"}])
    assert r.status_code == 200, r.text


def test_the_dimensions_are_named_as_in_the_objectives_catalogue(client, as_user, project, catalogue):
    catalogue.route("GET", "/api/control-objectives", (200, [
        {"id": "O1", "sub_requirement_label": "x", "macro_id": "R1", "macro_title": "Human Agency and Oversight"},
        {"id": "O21", "sub_requirement_label": "y", "macro_id": "R5", "macro_title": "Fairness"}]))
    evidence.forget_titles()
    titles = {d["id"]: d["title"] for d in get(client, as_user, project).json()["dimensions"]}
    assert titles["R5"] == "Fairness" and titles["R1"] == "Human Agency and Oversight"
    # one the catalogue does not name keeps the paper's name
    assert titles["R11"] == "Record-keeping and Documentation Retention"



# ── objective ids O1 ... O50 (2026-10-01) ───────────────────────────────────

def test_the_objectives_are_listed_in_catalogue_order_not_string_order(client, as_user, project, dsn):
    sql(dsn, project["pid"], "UPDATE control_objectives.objective_selection SET objective_ids = '{O10,O9,O24}'"
                             " WHERE project_id = 'a2'")
    body = get(client, as_user, project).json()
    assert [o["id"] for o in body["objectives"]] == ["O9", "O10", "O24"]


def test_an_objectives_dimension_is_unknown_when_its_catalogue_does_not_answer(
        client, as_user, project, monkeypatch):
    monkeypatch.setenv("CONTROL_OBJECTIVES_URL", "http://127.0.0.1:9")
    evidence.forget_titles()
    body = get(client, as_user, project).json()
    assert {o["dimension"] for o in body["objectives"]} == {None}
    assert body["dimensions_known"] is False


def test_template_0017_renames_old_ids_and_takes_only_new_ones(project, dsn):
    from pathlib import Path

    template = (Path(evidence.__file__).resolve().parent.parent / "project-template"
                / "0017_objective_ids.sql").read_text()
    pid = project["pid"]
    # a link stored before the rename, with the old check
    sql(dsn, pid, "ALTER TABLE evidence.link DROP CONSTRAINT IF EXISTS link_objective_id_check")
    sql(dsn, pid, "INSERT INTO evidence.link (objective_id, kind, item_key, created_by)"
                  " VALUES ('R6.1', 'control', 'ck1', 'a'), ('R11.4', 'test', 'x', 'a')")
    sql(dsn, pid, template)
    assert sql(dsn, pid, "SELECT objective_id FROM evidence.link ORDER BY objective_id") == [("O24",), ("O50",)]
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, pid, "INSERT INTO evidence.link (objective_id, kind, item_key, created_by)"
                      " VALUES ('R1.1', 'test', 'y', 'a')")
    # running it again changes nothing
    sql(dsn, pid, template)
    assert sql(dsn, pid, "SELECT count(*) FROM evidence.link") == [(2,)]



# ── the project's own objective sets (2026-10-01) ───────────────────────────

def _own_set(dsn, pid):
    """Set BNK: version 1 names BNK1 "Old wording"; version 2 names BNK1 "Sign-off" (R1), BNK9 and BNK10 (R6)."""
    sql(dsn, pid, "INSERT INTO control_objectives.objective_set_version VALUES ('v1', 's', 1), ('v2', 's', 2)")
    sql(dsn, pid, "INSERT INTO control_objectives.objective_set_version_item VALUES"
                  " ('v1', 'BNK1', 'Old wording', 'R1'), ('v2', 'BNK1', 'Sign-off', 'R1'),"
                  " ('v2', 'BNK9', 'Ninth', 'R6'), ('v2', 'BNK10', 'Tenth', 'R6')")
    sql(dsn, pid, "UPDATE control_objectives.objective_selection SET objective_ids = '{BNK10,O24,BNK1,BNK9,O1}'"
                  " WHERE project_id = 'a2'")


def test_the_projects_own_objectives_are_named_from_its_database(client, as_user, project, dsn):
    _own_set(dsn, project["pid"])
    body = get(client, as_user, project).json()
    assert [(o["id"], o["title"], o["dimension"]) for o in body["objectives"]] == [
        ("O1", "Risk management system", "R1"), ("O24", "Human oversight", "R6"),
        ("BNK1", "Sign-off", "R1"), ("BNK9", "Ninth", "R6"), ("BNK10", "Tenth", "R6")]


def test_an_own_objective_takes_links_in_its_dimension_only(client, as_user, project, dsn):
    _own_set(dsn, project["pid"])
    ok = put(client, as_user, project, [{"objective_id": "BNK9", "kind": "control", "key": "ck1"}])
    assert ok.status_code == 200, ok.text
    refused = put(client, as_user, project, [{"objective_id": "BNK1", "kind": "control", "key": "ck1"}])
    assert refused.status_code == 422 and "not in R1" in refused.text


def test_template_0018_takes_any_sets_ids(project, dsn):
    from pathlib import Path

    template = (Path(evidence.__file__).resolve().parent.parent / "project-template"
                / "0018_objective_set_ids.sql").read_text()
    pid = project["pid"]
    sql(dsn, pid, template)
    sql(dsn, pid, "INSERT INTO evidence.link (objective_id, kind, item_key, created_by)"
                  " VALUES ('BNK12', 'test', 'x', 'a'), ('O3', 'test', 'x', 'a')")
    for bad in ("bnk1", "B1", "BNK0", "R1.1"):
        with pytest.raises(psycopg.errors.CheckViolation):
            sql(dsn, pid, "INSERT INTO evidence.link (objective_id, kind, item_key, created_by)"
                          " VALUES (%s, 'test', 'y', 'a')", (bad,))
