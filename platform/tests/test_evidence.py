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
    catalogue_slug text, enabled boolean NOT NULL DEFAULT true, name text);
CREATE TABLE IF NOT EXISTS engine.aisc_backend_project (id serial PRIMARY KEY, name text NOT NULL, project_id uuid);
CREATE TABLE IF NOT EXISTS engine.aisc_backend_pluginconfig (id serial PRIMARY KEY, plugin_id int NOT NULL, name text);
CREATE TABLE IF NOT EXISTS engine.aisc_backend_evaluation (
    id serial PRIMARY KEY, status text NOT NULL, system_id uuid, created_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS engine.aisc_backend_aicomponent (id serial PRIMARY KEY, pid uuid NOT NULL);
CREATE TABLE IF NOT EXISTS engine.aisc_backend_evaluationinput (
    id serial PRIMARY KEY, evaluation_plugin_id int NOT NULL, name text NOT NULL, component_id int);
CREATE TABLE IF NOT EXISTS engine.aisc_backend_evaluationplugin (
    id serial PRIMARY KEY, evaluation_id int NOT NULL, plugin_config_id int, status text NOT NULL);
CREATE TABLE IF NOT EXISTS controls.checklist (id text PRIMARY KEY, "catalogueId" text, title text NOT NULL);
CREATE TABLE IF NOT EXISTS controls.checklist_question (
    id text PRIMARY KEY, "checklistId" text NOT NULL, "order" int NOT NULL, text text NOT NULL DEFAULT 'q');
CREATE TABLE IF NOT EXISTS controls.submission (
    id text PRIMARY KEY, "checklistId" text NOT NULL, label text NOT NULL DEFAULT 's', status text NOT NULL,
    version int NOT NULL DEFAULT 1, "previousVersionId" text UNIQUE, archived_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS controls.submission_answer (
    id text PRIMARY KEY, "submissionId" text NOT NULL, "questionId" text NOT NULL, answer text, score int);
CREATE TABLE IF NOT EXISTS control_objectives.objective_set_version (
    id varchar(32) PRIMARY KEY, set_id varchar(32) NOT NULL, number int NOT NULL);
CREATE TABLE IF NOT EXISTS control_objectives.objective_set_version_item (
    set_version_id varchar(32) NOT NULL, objective_id text NOT NULL, label text NOT NULL, dimension text NOT NULL,
    PRIMARY KEY (set_version_id, objective_id));
GRANT SELECT ON control_objectives.project, control_objectives.objective_selection,
    control_objectives.objective_set_version, control_objectives.objective_set_version_item,
    engine.aisc_backend_plugin, controls.checklist, engine.aisc_backend_project,
    engine.aisc_backend_evaluation, engine.aisc_backend_evaluationplugin, controls.checklist_question,
    controls.submission, controls.submission_answer, engine.aisc_backend_aicomponent,
    engine.aisc_backend_evaluationinput TO report_ro;
GRANT SELECT (id, plugin_id, name) ON engine.aisc_backend_pluginconfig TO report_ro;
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
        {"id": "O1", "sub_requirement_label": "Risk management system", "macro_id": "REQ1"},
        {"id": "O7", "sub_requirement_label": "Security incidents", "macro_id": "REQ2"},
        {"id": "O9", "sub_requirement_label": "Calibration", "macro_id": "REQ2"},
        {"id": "O10", "sub_requirement_label": "Safe state", "macro_id": "REQ2"},
        {"id": "O24", "sub_requirement_label": "Human oversight", "macro_id": "REQ6"}]))
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


V1, V2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
LB = {"objective_id": "O1", "kind": "test", "key": "aisc-plugin-langbite"}
GOV = {"objective_id": "O24", "kind": "control", "key": "ck1"}


# ── the table ───────────────────────────────────────────────────────────────

def test_the_evidence_schema_is_made_and_the_readers_read_it(project, dsn):
    cols = sql(dsn, project["pid"], "SELECT column_name FROM information_schema.columns"
                                    " WHERE table_schema = 'evidence' AND table_name = 'link' ORDER BY ordinal_position")
    assert [c[0] for c in cols] == ["objective_id", "kind", "item_key", "created_by", "created_at", "system_id"]
    rows = sql(dsn, project["pid"], "SELECT r, has_table_privilege(r, 'evidence.link', 'SELECT'),"
                                    " has_table_privilege(r, 'evidence.link', 'INSERT')"
                                    " FROM unnest(array['report_ro', 'dashboard_ro', 'report_composer_rw']) r"
                                    " WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r)")
    assert rows and all(sel and not ins for _, sel, ins in rows)
    # the composer copies the links into a report's snapshot when it issues one (D5)
    assert "report_composer_rw" in {r for r, _, _ in rows}


def test_a_link_is_one_objective_one_item(project, dsn):
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, project["pid"], "INSERT INTO evidence.link (system_id, objective_id, kind, item_key, created_by)"
                                 " VALUES ('22222222-2222-2222-2222-222222222222', 'O1', 'model', 'x', 'a')")


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
# Each objective belongs to the dimension of its macro-requirement (O7 -> REQ2). Each test and
# control takes its dimensions from its tags in the tools catalogue; a sub-dimension tag counts as
# its parent dimension. A link may only join an objective and an item of the same dimension.

def dim(slug):
    return {"slug": slug, "section": "dimension", "parent_dimension_slug": None}


def subdim(slug, parent):
    return {"slug": slug, "section": "testing_subdim", "parent_dimension_slug": parent}


TOOLS = [
    # in REQ1 directly and in REQ6 directly
    {"slug": "langbite", "package_name": "aisc-plugin-langbite",
     "tags": [{"slug": "test", "section": "type", "parent_dimension_slug": None},
              dim("human-agency-oversight"), dim("societal-environmental-wellbeing")]},
    # in REQ6 only through a sub-dimension
    {"slug": "promptfoo", "package_name": "aisc-plugin-promptfoo",
     "tags": [subdim("energy-use", "societal-environmental-wellbeing")]},
    # the checklist's catalogue entry, in REQ6
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
    assert [d["id"] for d in body["dimensions"]] == [f"REQ{n}" for n in range(1, 12)]
    assert body["dimensions"][0]["title"] == "Human Agency and Oversight"
    assert body["dimensions"][4]["title"] == "Diversity, Non-Discrimination and Fairness"
    assert body["dimensions_known"] is True


def test_an_objective_is_in_the_dimension_of_its_requirement(client, as_user, project):
    body = get(client, as_user, project).json()
    assert [(o["id"], o["dimension"]) for o in body["objectives"]] == [("O1", "REQ1"), ("O24", "REQ6")]


def test_tests_and_controls_take_their_dimensions_from_the_catalogue(client, as_user, project, tools):
    body = get(client, as_user, project).json()
    # LangBiTe has no catalogue slug stored here: it is found by its package name
    assert {t["key"]: t["dimensions"] for t in body["tests"]} == {
        "aisc-plugin-langbite": ["REQ1", "REQ6"], "aisc-plugin-promptfoo": ["REQ6"]}
    # the checklist is found by its catalogue id
    assert {c["key"]: c["dimensions"] for c in body["controls"]} == {"ck1": ["REQ6"]}
    assert tools.requests("GET", "/tool/")[0]["path"] == "/tool/?detailed=true"


def test_a_stored_catalogue_slug_wins_over_the_package_name(client, as_user, project, dsn):
    sql(dsn, project["pid"], "UPDATE engine.aisc_backend_plugin SET catalogue_slug = 'gov'"
                             " WHERE package_name = 'aisc-plugin-langbite'")
    body = get(client, as_user, project).json()
    assert {t["key"]: t["dimensions"] for t in body["tests"]}["aisc-plugin-langbite"] == ["REQ6"]


def test_an_item_with_no_dimension_in_the_catalogue_has_none(client, as_user, project, dsn):
    sql(dsn, project["pid"], "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name)"
                             " VALUES ('aisc-plugin-untagged', '1.0', 'Untagged'), ('aisc-plugin-local', '1.0', 'Local')")
    body = get(client, as_user, project).json()
    found = {t["key"]: t["dimensions"] for t in body["tests"]}
    assert found["aisc-plugin-untagged"] == [] and found["aisc-plugin-local"] == []


def test_a_link_across_dimensions_is_refused(client, as_user, project, dsn):
    sql(dsn, project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = true")
    r = put(client, as_user, project, [LB, {"objective_id": "O1", "kind": "control", "key": "ck1"}])
    assert r.status_code == 422 and "control ck1 is not in REQ1 Human Agency and Oversight" in r.text, r.text
    r = put(client, as_user, project, [{"objective_id": "O1", "kind": "test", "key": "aisc-plugin-promptfoo"}])
    assert r.status_code == 422 and "not in REQ1" in r.text, r.text
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
        {"id": "O1", "sub_requirement_label": "x", "macro_id": "REQ1", "macro_title": "Human Agency and Oversight"},
        {"id": "O21", "sub_requirement_label": "y", "macro_id": "REQ5", "macro_title": "Fairness"}]))
    evidence.forget_titles()
    titles = {d["id"]: d["title"] for d in get(client, as_user, project).json()["dimensions"]}
    assert titles["REQ5"] == "Fairness" and titles["REQ1"] == "Human Agency and Oversight"
    # one the catalogue does not name keeps the paper's name
    assert titles["REQ11"] == "Record-keeping and Documentation Retention"



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
    sql(dsn, pid, "INSERT INTO evidence.link (system_id, objective_id, kind, item_key, created_by)"
                  " VALUES (%(v)s, 'R6.1', 'control', 'ck1', 'a'), (%(v)s, 'R11.4', 'test', 'x', 'a')", {"v": V2})
    sql(dsn, pid, template)
    assert sql(dsn, pid, "SELECT objective_id FROM evidence.link ORDER BY objective_id") == [("O24",), ("O50",)]
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, pid, "INSERT INTO evidence.link (system_id, objective_id, kind, item_key, created_by)"
                      " VALUES (%(v)s, 'R1.1', 'test', 'y', 'a')", {"v": V2})
    # running it again changes nothing
    sql(dsn, pid, template)
    assert sql(dsn, pid, "SELECT count(*) FROM evidence.link") == [(2,)]



# ── the project's own objective sets (2026-10-01) ───────────────────────────

def _own_set(dsn, pid):
    """Set BNK: version 1 names BNK1 "Old wording"; version 2 names BNK1 "Sign-off" (REQ1), BNK9 and BNK10 (REQ6)."""
    sql(dsn, pid, "INSERT INTO control_objectives.objective_set_version VALUES ('v1', 's', 1), ('v2', 's', 2)")
    sql(dsn, pid, "INSERT INTO control_objectives.objective_set_version_item VALUES"
                  " ('v1', 'BNK1', 'Old wording', 'REQ1'), ('v2', 'BNK1', 'Sign-off', 'REQ1'),"
                  " ('v2', 'BNK9', 'Ninth', 'REQ6'), ('v2', 'BNK10', 'Tenth', 'REQ6')")
    sql(dsn, pid, "UPDATE control_objectives.objective_selection SET objective_ids = '{BNK10,O24,BNK1,BNK9,O1}'"
                  " WHERE project_id = 'a2'")


def test_the_projects_own_objectives_are_named_from_its_database(client, as_user, project, dsn):
    _own_set(dsn, project["pid"])
    body = get(client, as_user, project).json()
    assert [(o["id"], o["title"], o["dimension"]) for o in body["objectives"]] == [
        ("O1", "Risk management system", "REQ1"), ("O24", "Human oversight", "REQ6"),
        ("BNK1", "Sign-off", "REQ1"), ("BNK9", "Ninth", "REQ6"), ("BNK10", "Tenth", "REQ6")]


def test_an_own_objective_takes_links_in_its_dimension_only(client, as_user, project, dsn):
    _own_set(dsn, project["pid"])
    ok = put(client, as_user, project, [{"objective_id": "BNK9", "kind": "control", "key": "ck1"}])
    assert ok.status_code == 200, ok.text
    refused = put(client, as_user, project, [{"objective_id": "BNK1", "kind": "control", "key": "ck1"}])
    assert refused.status_code == 422 and "not in REQ1" in refused.text


def test_template_0018_takes_any_sets_ids(project, dsn):
    from pathlib import Path

    template = (Path(evidence.__file__).resolve().parent.parent / "project-template"
                / "0018_objective_set_ids.sql").read_text()
    pid = project["pid"]
    sql(dsn, pid, template)
    sql(dsn, pid, "INSERT INTO evidence.link (system_id, objective_id, kind, item_key, created_by)"
                  " VALUES (%(v)s, 'BNK12', 'test', 'x', 'a'), (%(v)s, 'O3', 'test', 'x', 'a')", {"v": V2})
    for bad in ("bnk1", "B1", "BNK0", "R1.1"):
        with pytest.raises(psycopg.errors.CheckViolation):
            sql(dsn, pid, "INSERT INTO evidence.link (system_id, objective_id, kind, item_key, created_by)"
                          " VALUES (%s, %s, 'test', 'y', 'a')", (V2, bad))



# ── the links belong to one AI card version (2026-10-02) ────────────────────

def _v3(dsn, pid, selected="{O1}"):
    """A third card version, the new latest, whose assessment selects `selected`."""
    v3 = "33333333-3333-3333-3333-333333333333"
    sql(dsn, pid, "INSERT INTO project.system (pid, number, name) VALUES (%s, 3, 'S')", (v3,))
    sql(dsn, pid, "INSERT INTO control_objectives.project VALUES ('a3', %s)", (v3,))
    sql(dsn, pid, "INSERT INTO control_objectives.objective_selection (project_id, objective_ids) VALUES ('a3', %s)",
        (selected,))
    return v3


def test_the_page_is_the_latest_versions_and_names_every_version(client, as_user, project):
    body = get(client, as_user, project).json()
    assert body["version"] == {"pid": V2, "number": 2}
    assert [v["number"] for v in body["versions"]] == [2, 1]
    assert body["read_only"] is False and body["carried_from"] is None


def test_links_are_saved_for_the_latest_version(client, as_user, project, dsn):
    put(client, as_user, project, [LB])
    assert sql(dsn, project["pid"], "SELECT system_id::text, objective_id FROM evidence.link") == [(V2, "O1")]


def test_an_older_version_reads_its_own_selection_and_cannot_change(client, as_user, project, dsn):
    put(client, as_user, project, [LB])
    older = client.get(f"/projects/{project['slug']}/evidence?version={V1}", headers=as_user(ALICE)).json()
    assert older["version"]["number"] == 1 and older["read_only"] is True
    assert [o["id"] for o in older["objectives"]] == ["O1", "O7"]
    assert older["links"] == []
    r = client.put(f"/projects/{project['slug']}/evidence/links", json={"links": [LB], "version": V1},
                   headers=as_user(ALICE))
    assert r.status_code == 409 and "version 1" in r.text


def test_a_version_not_in_the_project_is_404(client, as_user, project):
    r = client.get(f"/projects/{project['slug']}/evidence?version=99999999-9999-9999-9999-999999999999",
                   headers=as_user(ALICE))
    assert r.status_code == 404


def test_a_new_version_is_offered_the_previous_links_still_in_its_matrix(client, as_user, project, dsn):
    put(client, as_user, project, [LB, GOV])                     # v2: O1 <- LangBiTe, O24 <- checklist
    v3 = _v3(dsn, project["pid"], "{O1}")
    body = get(client, as_user, project).json()
    assert body["version"]["number"] == 3 and body["carried_from"] == 2
    assert [(l["objective_id"], l["key"], l["carried"]) for l in body["links"]] == [
        ("O1", "aisc-plugin-langbite", True)]                  # O24 is not in v3's matrix
    # nothing is written until the assessor saves
    assert sql(dsn, project["pid"], "SELECT count(*) FROM evidence.link WHERE system_id = %s", (v3,)) == [(0,)]
    saved = put(client, as_user, project, [LB]).json()
    assert saved["carried_from"] is None and [l["carried"] for l in saved["links"]] == [False]
    assert sql(dsn, project["pid"], "SELECT count(*) FROM evidence.link WHERE system_id = %s", (v3,)) == [(1,)]
    # version 2 keeps its own
    assert sql(dsn, project["pid"], "SELECT count(*) FROM evidence.link WHERE system_id = %s", (V2,)) == [(2,)]


def test_deleting_a_version_deletes_its_links(client, as_user, project, dsn):
    put(client, as_user, project, [LB])
    sql(dsn, project["pid"], "DELETE FROM control_objectives.project WHERE system_id = %s", (V2,))
    sql(dsn, project["pid"], "DELETE FROM project.system WHERE pid = %s", (V2,))
    assert sql(dsn, project["pid"], "SELECT count(*) FROM evidence.link") == [(0,)]


def test_template_0019_gives_every_link_its_version(project, dsn):
    from pathlib import Path

    folder = Path(evidence.__file__).resolve().parent.parent / "project-template"
    pid = project["pid"]
    # a link from before 0019, with no version
    sql(dsn, pid, "ALTER TABLE evidence.link DROP CONSTRAINT IF EXISTS link_pkey")
    sql(dsn, pid, "ALTER TABLE evidence.link DROP COLUMN system_id")
    sql(dsn, pid, "ALTER TABLE evidence.link ADD PRIMARY KEY (objective_id, kind, item_key)")
    sql(dsn, pid, "INSERT INTO evidence.link (objective_id, kind, item_key, created_by) VALUES ('O1', 'test', 'x', 'a')")
    sql(dsn, pid, (folder / "0019_evidence_per_version.sql").read_text())
    assert sql(dsn, pid, "SELECT system_id::text FROM evidence.link") == [(V2,)]     # the latest version
    keys = sql(dsn, pid, "SELECT pg_get_constraintdef(oid) FROM pg_constraint"
                         " WHERE conrelid = 'evidence.link'::regclass AND contype = 'p'")
    assert keys == [("PRIMARY KEY (system_id, objective_id, kind, item_key)",)]
    sql(dsn, pid, (folder / "0019_evidence_per_version.sql").read_text())           # again: no change
    assert sql(dsn, pid, "SELECT count(*) FROM evidence.link") == [(1,)]


# ── step 4 test tiles (2026-10-03): each test's engine name and its runs on the version shown ──

V1, V2 = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"


def _runs(dsn, pid, package, version, *statuses, evaluation_status="Done"):
    """One evaluation of `version` running `package` once per status (its per-plugin rows)."""
    plugin = sql(dsn, pid, "SELECT id FROM engine.aisc_backend_plugin WHERE package_name = %s", (package,))[0][0]
    config = sql(dsn, pid, "INSERT INTO engine.aisc_backend_pluginconfig (plugin_id, name) VALUES (%s, 'c')"
                           " RETURNING id", (plugin,))[0][0]
    for status in statuses:
        ev = sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluation (status, system_id) VALUES (%s, %s)"
                           " RETURNING id", (evaluation_status, version))[0][0]
        sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluationplugin (evaluation_id, plugin_config_id, status)"
                      " VALUES (%s, %s, %s)", (ev, config, status))


@pytest.fixture
def engine(project, dsn):
    pid = project["pid"]
    sql(dsn, pid, "INSERT INTO engine.aisc_backend_project (name, project_id) VALUES ('evd-workspace', %s)", (pid,))
    sql(dsn, pid, "UPDATE engine.aisc_backend_plugin SET name = 'LangBiTePlugin'"
                  " WHERE package_name = 'aisc-plugin-langbite'")
    sql(dsn, pid, "UPDATE engine.aisc_backend_plugin SET name = 'PromptfooPlugin'"
                  " WHERE package_name = 'aisc-plugin-promptfoo'")
    return project


def test_the_page_names_the_engine_workspace_and_each_tests_engine_name(client, as_user, engine):
    body = get(client, as_user, engine).json()
    assert body["engine_workspace"] == "evd-workspace"
    names = {t["key"]: t["engine_name"] for t in body["tests"]}
    assert names == {"aisc-plugin-langbite": "LangBiTePlugin", "aisc-plugin-promptfoo": "PromptfooPlugin"}


def test_each_test_counts_its_runs_on_the_version_shown(client, as_user, engine, dsn):
    pid = engine["pid"]
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", "Done", "Failed", "Running", "Pending")
    _runs(dsn, pid, "aisc-plugin-langbite", V1, "Done")
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", evaluation_status="Archived")   # hidden in the engine
    latest = {t["key"]: t["runs"] for t in get(client, as_user, engine).json()["tests"]}
    assert latest["aisc-plugin-langbite"] == {"executed": 2, "failed": 1, "running": 2}
    assert latest["aisc-plugin-promptfoo"] == {"executed": 0, "failed": 0, "running": 0}
    older = client.get(f"/projects/{engine['slug']}/evidence?version={V1}", headers=as_user(ALICE)).json()
    assert {t["key"]: t["runs"] for t in older["tests"]}["aisc-plugin-langbite"] == \
        {"executed": 1, "failed": 0, "running": 0}


def test_a_removed_test_has_no_engine_name_and_no_runs(client, as_user, engine, dsn):
    put(client, as_user, engine, [LB])
    sql(dsn, engine["pid"], "DELETE FROM engine.aisc_backend_plugin WHERE package_name = 'aisc-plugin-langbite'")
    tests = {t["key"]: t for t in get(client, as_user, engine).json()["tests"]}
    assert tests["aisc-plugin-langbite"]["stale"] == "removed"
    assert tests["aisc-plugin-langbite"]["engine_name"] is None and tests["aisc-plugin-langbite"]["runs"] is None


def test_no_engine_tables_yet_reads_as_no_runs(client, as_user, project, dsn):
    sql(dsn, project["pid"], "DROP TABLE engine.aisc_backend_evaluationplugin, engine.aisc_backend_evaluation,"
                             " engine.aisc_backend_project")
    body = get(client, as_user, project).json()
    assert body["engine_workspace"] is None
    assert all(t["runs"] == {"executed": 0, "failed": 0, "running": 0} for t in body["tests"])


# ── step 4 test tiles per engine plugin (2026-10-04): a package may ship several plugins ──────────
# data-monitor ships Data Drift and Data Anomaly. `tests` stays one entry per package (links, dimensions
# and the report key a test by its package); `plugins` is one entry per engine plugin, for the tiles.

def _two_plugin_package(dsn, pid, anomaly_enabled=True):
    sql(dsn, pid, "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name, enabled, name)"
                  " VALUES ('data-monitor', '0.4.0', 'Data Anomaly', %s, 'DataAnomalyPlugin'),"
                  "        ('data-monitor', '0.4.0', 'Data Drift', true, 'DataDriftPlugin')", (anomaly_enabled,))


def _plugin_runs(dsn, pid, name, version, *statuses):
    plugin = sql(dsn, pid, "SELECT id FROM engine.aisc_backend_plugin WHERE name = %s", (name,))[0][0]
    config = sql(dsn, pid, "INSERT INTO engine.aisc_backend_pluginconfig (plugin_id, name) VALUES (%s, 'c')"
                           " RETURNING id", (plugin,))[0][0]
    for status in statuses:
        ev = sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluation (status, system_id) VALUES ('Done', %s)"
                           " RETURNING id", (version,))[0][0]
        sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluationplugin (evaluation_id, plugin_config_id, status)"
                      " VALUES (%s, %s, %s)", (ev, config, status))


def test_p1_every_engine_plugin_is_listed_with_its_own_runs_even_when_two_share_a_package(client, as_user,
                                                                                       engine, dsn):
    pid = engine["pid"]
    _two_plugin_package(dsn, pid)
    _plugin_runs(dsn, pid, "DataDriftPlugin", V2, "Done", "Done", "Failed")
    _plugin_runs(dsn, pid, "DataAnomalyPlugin", V2, "Done")
    _plugin_runs(dsn, pid, "DataAnomalyPlugin", V1, "Done")                  # another card version
    body = get(client, as_user, engine).json()
    plugins = {p["engine_name"]: p for p in body["plugins"]}
    assert set(plugins) == {"LangBiTePlugin", "PromptfooPlugin", "DataAnomalyPlugin", "DataDriftPlugin"}
    assert plugins["DataDriftPlugin"] == {"key": "data-monitor", "engine_name": "DataDriftPlugin",
                                          "label": "Data Drift", "stale": None,
                                          "runs": {"executed": 2, "failed": 1, "running": 0}}
    assert plugins["DataAnomalyPlugin"]["label"] == "Data Anomaly"
    assert plugins["DataAnomalyPlugin"]["runs"] == {"executed": 1, "failed": 0, "running": 0}
    assert plugins["PromptfooPlugin"]["stale"] == "disabled"
    assert [p["label"] for p in body["plugins"]] == sorted(p["label"] for p in body["plugins"])


def test_p1_tests_stays_one_entry_per_package(client, as_user, engine, dsn):
    _two_plugin_package(dsn, engine["pid"])
    keys = [t["key"] for t in get(client, as_user, engine).json()["tests"]]
    assert sorted(keys) == ["aisc-plugin-langbite", "aisc-plugin-promptfoo", "data-monitor"]


def test_p1_a_disabled_plugin_says_so_on_its_own(client, as_user, engine, dsn):
    _two_plugin_package(dsn, engine["pid"], anomaly_enabled=False)
    plugins = {p["engine_name"]: p for p in get(client, as_user, engine).json()["plugins"]}
    assert plugins["DataAnomalyPlugin"]["stale"] == "disabled" and plugins["DataDriftPlugin"]["stale"] is None


def _upgraded_langbite(dsn, pid):
    """LangBiTe upgraded in the engine (as on mcas 2026-10-05): the engine keeps the old version's row,
    disabled, next to the new one, since a run takes the lowest enabled version."""
    sql(dsn, pid, "UPDATE engine.aisc_backend_plugin SET version = '0.2.4', enabled = false"
                  " WHERE name = 'LangBiTePlugin'")
    sql(dsn, pid, "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name, enabled, name)"
                  " VALUES ('aisc-plugin-langbite', '0.2.6', 'LangBiTe', true, 'LangBiTePlugin')")


def test_p1_an_upgraded_plugin_has_one_tile_with_every_versions_runs(client, as_user, engine, dsn):
    pid = engine["pid"]
    _upgraded_langbite(dsn, pid)
    old, new = (r[0] for r in sql(dsn, pid, "SELECT id FROM engine.aisc_backend_plugin"
                                            " WHERE name = 'LangBiTePlugin' ORDER BY version"))
    for plugin_id, statuses in ((old, ("Done", "Failed")), (new, ("Done",))):
        config = sql(dsn, pid, "INSERT INTO engine.aisc_backend_pluginconfig (plugin_id, name) VALUES (%s, 'c')"
                               " RETURNING id", (plugin_id,))[0][0]
        for status in statuses:
            ev = sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluation (status, system_id)"
                               " VALUES ('Done', %s) RETURNING id", (V2,))[0][0]
            sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluationplugin (evaluation_id, plugin_config_id,"
                          " status) VALUES (%s, %s, %s)", (ev, config, status))
    tiles = [p for p in get(client, as_user, engine).json()["plugins"] if p["engine_name"] == "LangBiTePlugin"]
    assert tiles == [{"key": "aisc-plugin-langbite", "engine_name": "LangBiTePlugin", "label": "LangBiTe",
                      "stale": None, "runs": {"executed": 2, "failed": 1, "running": 0}}]


def test_p1_an_upgraded_test_is_not_disabled_whichever_row_comes_last(client, as_user, engine, dsn):
    _upgraded_langbite(dsn, engine["pid"])
    sql(dsn, engine["pid"], "UPDATE engine.aisc_backend_plugin SET id = id + 100 WHERE enabled = false")
    tests = {t["key"]: t for t in get(client, as_user, engine).json()["tests"]}
    assert tests["aisc-plugin-langbite"]["stale"] is None


def test_p1_a_plugin_disabled_in_every_version_still_says_so(client, as_user, engine, dsn):
    _upgraded_langbite(dsn, engine["pid"])
    sql(dsn, engine["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = false WHERE name = 'LangBiTePlugin'")
    body = get(client, as_user, engine).json()
    tiles = [p for p in body["plugins"] if p["engine_name"] == "LangBiTePlugin"]
    assert len(tiles) == 1 and tiles[0]["stale"] == "disabled"
    assert {t["key"]: t for t in body["tests"]}["aisc-plugin-langbite"]["stale"] == "disabled"


def test_p1_no_engine_tables_yet_reads_as_no_runs_for_every_plugin(client, as_user, project, dsn):
    sql(dsn, project["pid"], "DROP TABLE engine.aisc_backend_evaluationplugin, engine.aisc_backend_evaluation,"
                             " engine.aisc_backend_project")
    body = get(client, as_user, project).json()
    assert body["plugins"] and all(p["runs"] == {"executed": 0, "failed": 0, "running": 0} for p in body["plugins"])


# ── step 4 control tiles (2026-10-03): each checklist's latest answers, as the controls app shows them ──

def _questions(dsn, pid, checklist, n):
    for i in range(n):
        sql(dsn, pid, "INSERT INTO controls.checklist_question (id, \"checklistId\", \"order\") VALUES (%s, %s, %s)",
            (f"{checklist}-q{i}", checklist, i))


def _submission(dsn, pid, sid, checklist, version, status, answers, previous=None, archived=False, age_s=0):
    """answers: [(score, answer text), ...] on the first questions."""
    sql(dsn, pid, "INSERT INTO controls.submission (id, \"checklistId\", status, version, \"previousVersionId\","
                  " archived_at, updated_at) VALUES (%s, %s, %s, %s, %s, CASE WHEN %s THEN now() END,"
                  " now() - make_interval(secs => %s))", (sid, checklist, status, version, previous, archived, age_s))
    for i, (score, text) in enumerate(answers):
        sql(dsn, pid, "INSERT INTO controls.submission_answer (id, \"submissionId\", \"questionId\", answer, score)"
                      " VALUES (%s, %s, %s, %s, %s)", (f"{sid}-a{i}", sid, f"{checklist}-q{i}", text, score))


def test_a_checklist_never_answered_has_its_questions_and_no_submission(client, as_user, project, dsn):
    _questions(dsn, project["pid"], "ck1", 4)
    ck = {c["key"]: c for c in get(client, as_user, project).json()["controls"]}["ck1"]
    assert ck["questions"] == 4 and ck["submission"] is None


def test_a_checklist_shows_its_latest_version_score_and_completion(client, as_user, project, dsn):
    pid = project["pid"]
    _questions(dsn, pid, "ck1", 4)
    _submission(dsn, pid, "s1", "ck1", 1, "Closed", [(1, "x"), (1, "x"), (1, "x"), (1, "x")], age_s=60)
    # v2 continues v1: scores 5, 4 and a written answer without a score; the fourth question is open
    _submission(dsn, pid, "s2", "ck1", 2, "Draft", [(5, "x"), (4, None), (None, "only words")], previous="s1")
    ck = {c["key"]: c for c in get(client, as_user, project).json()["controls"]}["ck1"]
    # readiness as the controls app computes it: (mean - 1) / 4, rounded half up (4.5 -> 87.5 -> 88%)
    assert ck["submission"] == {"id": "s2", "version": 2, "status": "Draft", "readiness": 88, "answered": 3}
    assert ck["questions"] == 4


def test_an_archived_chain_is_not_shown_and_nothing_scored_has_no_readiness(client, as_user, project, dsn):
    pid = project["pid"]
    _questions(dsn, pid, "ck1", 2)
    _submission(dsn, pid, "old", "ck1", 3, "Closed", [(5, "x"), (5, "x")], archived=True)
    _submission(dsn, pid, "new", "ck1", 1, "Draft", [(None, " ")], age_s=30)
    ck = {c["key"]: c for c in get(client, as_user, project).json()["controls"]}["ck1"]
    assert ck["submission"] == {"id": "new", "version": 1, "status": "Draft", "readiness": None, "answered": 0}


def test_a_deleted_checklist_has_no_questions_and_no_submission(client, as_user, project, dsn):
    put(client, as_user, project, [GOV])
    sql(dsn, project["pid"], "DELETE FROM controls.checklist WHERE id = 'ck1'")
    ck = {c["key"]: c for c in get(client, as_user, project).json()["controls"]}["ck1"]
    assert ck["stale"] == "deleted" and ck["questions"] is None and ck["submission"] is None


# ── results navigation (2026-10-03, docs/superpowers/results-nav-2026-10-03/01-specs.md R2) ──

COMP = "component:aaaaaaaa-0000-4000-8000-000000000001"
GONE = "component:aaaaaaaa-0000-4000-8000-000000000002"
ENG_COMP, ENG_GONE = "bbbbbbbb-0000-4000-8000-000000000001", "bbbbbbbb-0000-4000-8000-000000000002"


@pytest.fixture
def targets(engine, dsn):
    """The system (MCAS), a current component (Explanation assistant, LLM, in card 2) and one the
    latest card no longer lists (Old model, last in card 1), each mirrored in the engine."""
    pid = engine["pid"]
    sql(dsn, pid, "UPDATE target.target SET label = 'MCAS', last_card_number = 2 WHERE key = 'system'")
    sql(dsn, pid, "INSERT INTO target.target (key, kind, component_kind, label, first_card_number,"
                  " last_card_number, engine_component) VALUES"
                  " (%s, 'component', 'llm', 'Explanation assistant', 1, 2, %s),"
                  " (%s, 'component', 'model', 'Old model', 1, 1, %s)", (COMP, ENG_COMP, GONE, ENG_GONE))
    sql(dsn, pid, "INSERT INTO engine.aisc_backend_aicomponent (id, pid) VALUES (1, %s), (2, %s)",
        (ENG_COMP, ENG_GONE))
    return engine


def _run(dsn, pid, package, version, status, component=None, when="2026-10-01 10:00+00"):
    """One evaluation of `version` running `package` once, on the engine component `component`
    (an evaluation input named target), or with no target input."""
    plugin = sql(dsn, pid, "SELECT id FROM engine.aisc_backend_plugin WHERE package_name = %s", (package,))[0][0]
    config = sql(dsn, pid, "INSERT INTO engine.aisc_backend_pluginconfig (plugin_id, name) VALUES (%s, 'c')"
                           " RETURNING id", (plugin,))[0][0]
    ev = sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluation (status, system_id, created_at)"
                       " VALUES ('Done', %s, %s) RETURNING id", (version, when))[0][0]
    ep = sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluationplugin (evaluation_id, plugin_config_id, status)"
                       " VALUES (%s, %s, %s) RETURNING id", (ev, config, status))[0][0]
    if component is not None:
        sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluationinput (evaluation_plugin_id, name, component_id)"
                      " VALUES (%s, 'target', %s)", (ep, component))


def _targets(client, as_user, project, version=None):
    url = f"/projects/{project['slug']}/evidence" + (f"?version={version}" if version else "")
    return client.get(url, headers=as_user(ALICE)).json()["targets"]


def test_r2_1_targets_are_listed_system_first_then_components_by_label(client, as_user, targets):
    got = _targets(client, as_user, targets)
    assert [(t["key"], t["kind"], t["component_kind"], t["label"], t["stale"]) for t in got] == [
        ("system", "system", None, "MCAS", False),
        (COMP, "component", "llm", "Explanation assistant", False),
        (GONE, "component", "model", "Old model", True),
    ]
    assert all(t["tools"] == [] for t in got)


def test_r2_2_r2_3_each_target_counts_its_tools_runs_on_the_version_shown(client, as_user, targets, dsn):
    pid = targets["pid"]
    _run(dsn, pid, "aisc-plugin-langbite", V2, "Done", component=1, when="2026-09-30 08:00+00")
    _run(dsn, pid, "aisc-plugin-langbite", V2, "Failed", component=1, when="2026-10-01 09:30+00")
    _run(dsn, pid, "aisc-plugin-langbite", V2, "Running", component=1, when="2026-09-29 08:00+00")
    _run(dsn, pid, "aisc-plugin-promptfoo", V2, "Done", component=1)
    _run(dsn, pid, "aisc-plugin-langbite", V1, "Done", component=1)          # another version
    _run(dsn, pid, "aisc-plugin-langbite", V2, "Done", component=2)          # the stale component
    got = {t["key"]: t for t in _targets(client, as_user, targets)}
    assert got[COMP]["tools"] == [
        {"key": "aisc-plugin-langbite", "label": "LangBiTe", "executed": 1, "failed": 1, "running": 1,
         "last_run": "2026-10-01T09:30:00+00:00"},
        {"key": "aisc-plugin-promptfoo", "label": "Promptfoo", "executed": 1, "failed": 0, "running": 0,
         "last_run": "2026-10-01T10:00:00+00:00"},
    ]
    assert [t["key"] for t in got[GONE]["tools"]] == ["aisc-plugin-langbite"]
    assert got["system"]["tools"] == []
    older = {t["key"]: t for t in _targets(client, as_user, targets, V1)}
    assert [(t["key"], t["executed"]) for t in older[COMP]["tools"]] == [("aisc-plugin-langbite", 1)]


def test_r2_4_runs_with_no_target_are_one_more_entry_last_only_when_there_are_some(client, as_user, targets, dsn):
    assert all(t["kind"] != "unassigned" for t in _targets(client, as_user, targets))
    _run(dsn, targets["pid"], "aisc-plugin-langbite", V2, "Done")
    last = _targets(client, as_user, targets)[-1]
    assert (last["key"], last["kind"], last["label"]) == (None, "unassigned", "No target")
    assert [(t["key"], t["executed"]) for t in last["tools"]] == [("aisc-plugin-langbite", 1)]


def test_r2_6_no_target_table_reads_as_no_targets(client, as_user, project, dsn):
    sql(dsn, project["pid"], "DROP TABLE engine.aisc_backend_evaluationinput")
    sql(dsn, project["pid"], "ALTER TABLE target.target RENAME TO target_gone")
    assert _targets(client, as_user, project) == []
