"""Collect evidence: which tests and controls give evidence for which selected control
objective, many to many, per project.

The links live in the project's own database (schema `evidence`, template 0016), written only by
the platform. What can be linked is read, as report_ro, from the other steps' tables in the
same database: the objectives selected in step 2 (control_objectives.objective_selection, of the
latest card version that has one), the installed plugins (engine.aisc_backend_plugin) and the
installed checklists (controls.checklist). Those tables belong to their modules; here they are
stood in for with the columns this reads, granted to report_ro as the modules grant them.

Stale: a link whose objective is no longer selected, whose plugin is disabled or removed, or
whose checklist is gone is kept and shown with its reason; no new link may be made to it.
"""
from __future__ import annotations

import json
import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import evidence, projectdb
from tests.conftest import needs_database
from tests.http_stub import Stub

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
CREATE TABLE IF NOT EXISTS engine.aisc_backend_aicomponent (id serial PRIMARY KEY, pid uuid NOT NULL, name text);
CREATE TABLE IF NOT EXISTS engine.aisc_backend_evaluationinput (
    id serial PRIMARY KEY, evaluation_plugin_id int NOT NULL, name text NOT NULL, component_id int,
    value jsonb NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS engine.aisc_backend_evaluationplugin (
    id serial PRIMARY KEY, pid uuid NOT NULL DEFAULT gen_random_uuid(), evaluation_id int NOT NULL,
    plugin_config_id int, status text NOT NULL);
CREATE TABLE IF NOT EXISTS controls.checklist (id text PRIMARY KEY, "catalogueId" text, title text NOT NULL);
CREATE TABLE IF NOT EXISTS controls.checklist_question (
    id text PRIMARY KEY, "checklistId" text NOT NULL, "order" int NOT NULL, text text NOT NULL DEFAULT 'q');
CREATE TABLE IF NOT EXISTS controls.submission (
    id text PRIMARY KEY, "checklistId" text NOT NULL, label text NOT NULL DEFAULT 's', status text NOT NULL,
    version int NOT NULL DEFAULT 1, "previousVersionId" text UNIQUE, archived_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS controls.submission_answer (
    id text PRIMARY KEY, "submissionId" text NOT NULL, "questionId" text, answer text, score int);
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
def evidence_project(make_project, dsn):
    """A project with Bob as editor and Vera as viewer, whose steps 2 and 3 have made their choices:
    v1 selected O1 and O7, v2 (the latest) selects O1 and O24; LangBiTe and Promptfoo are
    installed (Promptfoo disabled); one checklist is installed."""
    p = make_project(editors=(BOB,), viewers=(VERA,))
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

def test_the_evidence_schema_is_made_and_the_readers_read_it(evidence_project, dsn):
    cols = sql(dsn, evidence_project["pid"],
               "SELECT column_name FROM information_schema.columns"
               " WHERE table_schema = 'evidence' AND table_name = 'link' ORDER BY ordinal_position")
    assert [c[0] for c in cols] == ["objective_id", "kind", "item_key", "created_by", "created_at", "system_id"]
    rows = sql(dsn, evidence_project["pid"], "SELECT r, has_table_privilege(r, 'evidence.link', 'SELECT'),"
                                             " has_table_privilege(r, 'evidence.link', 'INSERT')"
                                             " FROM unnest(array['report_ro', 'dashboard_ro', 'report_composer_rw']) r"
                                             " WHERE EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r)")
    assert rows and all(sel and not ins for _, sel, ins in rows)
    # The composer copies the links into a report's snapshot when it issues one
    assert "report_composer_rw" in {r for r, _, _ in rows}


def test_a_link_is_one_objective_one_item(evidence_project, dsn):
    with pytest.raises(psycopg.errors.CheckViolation):
        sql(dsn, evidence_project["pid"],
            "INSERT INTO evidence.link (system_id, objective_id, kind, item_key, created_by)"
                                          " VALUES ('22222222-2222-2222-2222-222222222222', 'O1', 'model', 'x', 'a')")


# ── what the page lists ─────────────────────────────────────────────────────

def test_the_page_lists_the_latest_selection_the_plugins_and_the_checklists(client, as_user, evidence_project):
    body = get(client, as_user, evidence_project).json()
    assert [(o["id"], o["stale"]) for o in body["objectives"]] == [("O1", None), ("O24", None)]
    assert [(t["key"], t["label"], t["stale"]) for t in body["tests"]] == [
        ("aisc-plugin-langbite", "LangBiTe", None), ("aisc-plugin-promptfoo", "Promptfoo", "disabled")]
    assert [(c["key"], c["label"], c["stale"]) for c in body["controls"]] == [("ck1", "Governance", None)]
    assert body["links"] == [] and body["can_edit"] is True


def test_a_project_whose_steps_have_nothing_yet_lists_nothing(client, as_user, project):
    body = client.get(f"/projects/{project['slug']}/evidence", headers=as_user(ALICE)).json()
    assert (body["objectives"], body["tests"], body["controls"], body["links"]) == ([], [], [], [])


def test_a_viewer_reads_and_may_not_edit(client, as_user, evidence_project):
    body = get(client, as_user, evidence_project, VERA)
    assert body.status_code == 200 and body.json()["can_edit"] is False
    assert put(client, as_user, evidence_project, [LB], VERA).status_code == 403


def test_a_stranger_gets_404(client, as_user, evidence_project):
    stranger = "00000000-0000-0000-0000-0000000057a4"
    assert get(client, as_user, evidence_project, stranger).status_code == 404
    assert put(client, as_user, evidence_project, [LB], stranger).status_code == 404


def test_the_objectives_are_named_from_the_catalogue(client, as_user, evidence_project):
    body = get(client, as_user, evidence_project).json()
    assert [(o["id"], o["title"]) for o in body["objectives"]] == [
        ("O1", "Risk management system"), ("O24", "Human oversight")]


def test_a_catalogue_that_is_down_leaves_the_names_empty(client, as_user, evidence_project, catalogue, monkeypatch):
    monkeypatch.setenv("CONTROL_OBJECTIVES_URL", "http://127.0.0.1:9")
    evidence.forget_titles()
    body = get(client, as_user, evidence_project)
    assert body.status_code == 200 and [o["title"] for o in body.json()["objectives"]] == ["", ""]


# ── linking (many to many) ──────────────────────────────────────────────────

def test_an_editor_links_tests_and_controls_to_objectives(client, as_user, evidence_project, dsn):
    both = {"objective_id": "O24", "kind": "test", "key": "aisc-plugin-langbite"}
    r = put(client, as_user, evidence_project, [LB, GOV, both], BOB)
    assert r.status_code == 200, r.text
    assert sorted((link["objective_id"], link["kind"], link["key"]) for link in r.json()["links"]) == [
        ("O1", "test", "aisc-plugin-langbite"), ("O24", "control", "ck1"), ("O24", "test", "aisc-plugin-langbite")]
    assert sql(dsn, evidence_project["pid"], "SELECT count(*) FROM evidence.link") == [(3,)]
    assert sql(dsn, evidence_project["pid"], "SELECT DISTINCT created_by FROM evidence.link") == [(BOB,)]


def test_saving_replaces_the_links_and_keeps_who_made_the_old_ones(client, as_user, evidence_project, dsn):
    put(client, as_user, evidence_project, [LB, GOV], BOB)
    r = put(client, as_user, evidence_project, [LB], ALICE)
    assert [(link["objective_id"], link["key"]) for link in r.json()["links"]] == [("O1", "aisc-plugin-langbite")]
    assert sql(dsn, evidence_project["pid"], "SELECT created_by FROM evidence.link") == [(BOB,)]


@pytest.mark.parametrize("link, why", [
    ({"objective_id": "O7", "kind": "test", "key": "aisc-plugin-langbite"}, "O7 is not selected"),
    ({"objective_id": "O1", "kind": "test", "key": "aisc-plugin-promptfoo"}, "disabled"),
    ({"objective_id": "O1", "kind": "test", "key": "aisc-plugin-nothing"}, "not installed"),
    ({"objective_id": "O1", "kind": "control", "key": "ck9"}, "not installed"),
    ({"objective_id": "O1", "kind": "model", "key": "ck1"}, "kind"),
])
def test_a_new_link_to_something_not_there_is_refused(client, as_user, evidence_project, link, why, dsn):
    r = put(client, as_user, evidence_project, [LB, link])
    assert r.status_code == 422 and why in r.text, r.text
    assert sql(dsn, evidence_project["pid"], "SELECT count(*) FROM evidence.link") == [(0,)]


# ── stale ───────────────────────────────────────────────────────────────────

def test_links_that_went_stale_are_kept_and_shown_with_their_reason(client, as_user, evidence_project, dsn):
    promptfoo_on_r6 = {"objective_id": "O24", "kind": "test", "key": "aisc-plugin-promptfoo"}
    sql(dsn, evidence_project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = true")
    put(client, as_user, evidence_project, [LB, GOV, promptfoo_on_r6])
    # step 2 unselects O24, the engine disables Promptfoo, the checklist is deleted
    sql(dsn, evidence_project["pid"], "UPDATE control_objectives.objective_selection SET objective_ids = '{O1}'"
                                      " WHERE project_id = 'a2'")
    sql(dsn, evidence_project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = false"
                                      " WHERE package_name = 'aisc-plugin-promptfoo'")
    sql(dsn, evidence_project["pid"], "DELETE FROM controls.checklist")
    body = get(client, as_user, evidence_project).json()
    assert [(o["id"], o["stale"]) for o in body["objectives"]] == [("O1", None), ("O24", "not selected")]
    assert [(c["key"], c["label"], c["stale"]) for c in body["controls"]] == [("ck1", "ck1", "deleted")]
    stale = {(link["objective_id"], link["key"]): link["stale"] for link in body["links"]}
    assert stale == {("O1", "aisc-plugin-langbite"): None, ("O24", "ck1"): "not selected",
                     ("O24", "aisc-plugin-promptfoo"): "not selected"}
    # saving the page as it is keeps the stale links
    r = put(client, as_user, evidence_project, [{k: link[k] for k in ("objective_id", "kind",
                                                                   "key")} for link in body["links"]])
    assert r.status_code == 200, r.text
    assert sql(dsn, evidence_project["pid"], "SELECT count(*) FROM evidence.link") == [(3,)]


def test_a_removed_plugin_is_listed_as_removed_while_a_link_names_it(client, as_user, evidence_project, dsn):
    put(client, as_user, evidence_project, [LB])
    sql(dsn, evidence_project["pid"],
        "DELETE FROM engine.aisc_backend_plugin WHERE package_name = 'aisc-plugin-langbite'")
    body = get(client, as_user, evidence_project).json()
    assert ("aisc-plugin-langbite", "removed") in [(t["key"], t["stale"]) for t in body["tests"]]
    assert body["links"][0]["stale"] == "removed"


# ── trustworthiness dimensions ──────────────────────────────────────────────
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


def test_the_page_lists_the_eleven_dimensions_in_order(client, as_user, evidence_project):
    body = get(client, as_user, evidence_project).json()
    assert [d["id"] for d in body["dimensions"]] == [f"REQ{n}" for n in range(1, 12)]
    assert body["dimensions"][0]["title"] == "Human Agency and Oversight"
    assert body["dimensions"][4]["title"] == "Diversity, Non-Discrimination and Fairness"
    assert body["dimensions_known"] is True


def test_an_objective_is_in_the_dimension_of_its_requirement(client, as_user, evidence_project):
    body = get(client, as_user, evidence_project).json()
    assert [(o["id"], o["dimension"]) for o in body["objectives"]] == [("O1", "REQ1"), ("O24", "REQ6")]


def test_tests_and_controls_take_their_dimensions_from_the_catalogue(client, as_user, evidence_project, tools):
    body = get(client, as_user, evidence_project).json()
    # LangBiTe has no catalogue slug stored here: it is found by its package name
    assert {t["key"]: t["dimensions"] for t in body["tests"]} == {
        "aisc-plugin-langbite": ["REQ1", "REQ6"], "aisc-plugin-promptfoo": ["REQ6"]}
    # the checklist is found by its catalogue id
    assert {c["key"]: c["dimensions"] for c in body["controls"]} == {"ck1": ["REQ6"]}
    assert tools.requests("GET", "/tool/")[0]["path"] == "/tool/?detailed=true"


def test_a_stored_catalogue_slug_wins_over_the_package_name(client, as_user, evidence_project, dsn):
    sql(dsn, evidence_project["pid"], "UPDATE engine.aisc_backend_plugin SET catalogue_slug = 'gov'"
                                      " WHERE package_name = 'aisc-plugin-langbite'")
    body = get(client, as_user, evidence_project).json()
    assert {t["key"]: t["dimensions"] for t in body["tests"]}["aisc-plugin-langbite"] == ["REQ6"]


def test_an_item_with_no_dimension_in_the_catalogue_has_none(client, as_user, evidence_project, dsn):
    sql(dsn, evidence_project["pid"],
        "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name)"
        " VALUES ('aisc-plugin-untagged', '1.0', 'Untagged'), ('aisc-plugin-local', '1.0', 'Local')")
    body = get(client, as_user, evidence_project).json()
    found = {t["key"]: t["dimensions"] for t in body["tests"]}
    assert found["aisc-plugin-untagged"] == [] and found["aisc-plugin-local"] == []


def test_a_link_across_dimensions_is_refused(client, as_user, evidence_project, dsn):
    sql(dsn, evidence_project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = true")
    r = put(client, as_user, evidence_project, [LB, {"objective_id": "O1", "kind": "control", "key": "ck1"}])
    assert r.status_code == 422 and "control ck1 is not in REQ1 Human Agency and Oversight" in r.text, r.text
    r = put(client, as_user, evidence_project, [{"objective_id": "O1", "kind": "test", "key": "aisc-plugin-promptfoo"}])
    assert r.status_code == 422 and "not in REQ1" in r.text, r.text
    assert sql(dsn, evidence_project["pid"], "SELECT count(*) FROM evidence.link") == [(0,)]


def test_a_link_within_a_dimension_reached_through_a_sub_dimension_is_kept(client, as_user, evidence_project, dsn):
    sql(dsn, evidence_project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = true")
    r = put(client, as_user, evidence_project, [{"objective_id": "O24", "kind": "test",
                                                 "key": "aisc-plugin-promptfoo"}])
    assert r.status_code == 200, r.text


def test_a_catalogue_that_is_down_leaves_the_dimensions_unknown_and_refuses_nothing_for_them(
        client, as_user, evidence_project, monkeypatch):
    monkeypatch.setenv("CATALOGUE_URL", "http://127.0.0.1:9")
    evidence.forget_dimensions()
    body = get(client, as_user, evidence_project).json()
    assert body["dimensions_known"] is False
    assert {t["dimensions"] for t in body["tests"]} == {None}
    r = put(client, as_user, evidence_project, [{"objective_id": "O1", "kind": "control", "key": "ck1"}])
    assert r.status_code == 200, r.text


def test_the_dimensions_are_named_as_in_the_objectives_catalogue(client, as_user, evidence_project, catalogue):
    catalogue.route("GET", "/api/control-objectives", (200, [
        {"id": "O1", "sub_requirement_label": "x", "macro_id": "REQ1", "macro_title": "Human Agency and Oversight"},
        {"id": "O21", "sub_requirement_label": "y", "macro_id": "REQ5", "macro_title": "Fairness"}]))
    evidence.forget_titles()
    titles = {d["id"]: d["title"] for d in get(client, as_user, evidence_project).json()["dimensions"]}
    assert titles["REQ5"] == "Fairness" and titles["REQ1"] == "Human Agency and Oversight"
    # one the catalogue does not name keeps the paper's name
    assert titles["REQ11"] == "Record-keeping and Documentation Retention"



# ── objective ids O1 ... O50 ────────────────────────────────────────────────

def test_the_objectives_are_listed_in_catalogue_order_not_string_order(client, as_user, evidence_project, dsn):
    sql(dsn, evidence_project["pid"], "UPDATE control_objectives.objective_selection SET objective_ids = '{O10,O9,O24}'"
                                      " WHERE project_id = 'a2'")
    body = get(client, as_user, evidence_project).json()
    assert [o["id"] for o in body["objectives"]] == ["O9", "O10", "O24"]


def test_an_objectives_dimension_is_unknown_when_its_catalogue_does_not_answer(
        client, as_user, evidence_project, monkeypatch):
    monkeypatch.setenv("CONTROL_OBJECTIVES_URL", "http://127.0.0.1:9")
    evidence.forget_titles()
    body = get(client, as_user, evidence_project).json()
    assert {o["dimension"] for o in body["objectives"]} == {None}
    assert body["dimensions_known"] is False


def test_template_0017_renames_old_ids_and_takes_only_new_ones(evidence_project, dsn):
    from pathlib import Path

    template = (Path(evidence.__file__).resolve().parent.parent / "project-template"
                / "0017_objective_ids.sql").read_text()
    pid = evidence_project["pid"]
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



# ── the project's own objective sets ────────────────────────────────────────

def _own_set(dsn, pid):
    """Set BNK: version 1 names BNK1 "Old wording"; version 2 names BNK1 "Sign-off" (REQ1), BNK9 and BNK10 (REQ6)."""
    sql(dsn, pid, "INSERT INTO control_objectives.objective_set_version VALUES ('v1', 's', 1), ('v2', 's', 2)")
    sql(dsn, pid, "INSERT INTO control_objectives.objective_set_version_item VALUES"
                  " ('v1', 'BNK1', 'Old wording', 'REQ1'), ('v2', 'BNK1', 'Sign-off', 'REQ1'),"
                  " ('v2', 'BNK9', 'Ninth', 'REQ6'), ('v2', 'BNK10', 'Tenth', 'REQ6')")
    sql(dsn, pid, "UPDATE control_objectives.objective_selection SET objective_ids = '{BNK10,O24,BNK1,BNK9,O1}'"
                  " WHERE project_id = 'a2'")


def test_the_projects_own_objectives_are_named_from_its_database(client, as_user, evidence_project, dsn):
    _own_set(dsn, evidence_project["pid"])
    body = get(client, as_user, evidence_project).json()
    assert [(o["id"], o["title"], o["dimension"]) for o in body["objectives"]] == [
        ("O1", "Risk management system", "REQ1"), ("O24", "Human oversight", "REQ6"),
        ("BNK1", "Sign-off", "REQ1"), ("BNK9", "Ninth", "REQ6"), ("BNK10", "Tenth", "REQ6")]


def test_an_own_objective_takes_links_in_its_dimension_only(client, as_user, evidence_project, dsn):
    _own_set(dsn, evidence_project["pid"])
    ok = put(client, as_user, evidence_project, [{"objective_id": "BNK9", "kind": "control", "key": "ck1"}])
    assert ok.status_code == 200, ok.text
    refused = put(client, as_user, evidence_project, [{"objective_id": "BNK1", "kind": "control", "key": "ck1"}])
    assert refused.status_code == 422 and "not in REQ1" in refused.text


def test_template_0018_takes_any_sets_ids(evidence_project, dsn):
    from pathlib import Path

    template = (Path(evidence.__file__).resolve().parent.parent / "project-template"
                / "0018_objective_set_ids.sql").read_text()
    pid = evidence_project["pid"]
    sql(dsn, pid, template)
    sql(dsn, pid, "INSERT INTO evidence.link (system_id, objective_id, kind, item_key, created_by)"
                  " VALUES (%(v)s, 'BNK12', 'test', 'x', 'a'), (%(v)s, 'O3', 'test', 'x', 'a')", {"v": V2})
    for bad in ("bnk1", "B1", "BNK0", "R1.1"):
        with pytest.raises(psycopg.errors.CheckViolation):
            sql(dsn, pid, "INSERT INTO evidence.link (system_id, objective_id, kind, item_key, created_by)"
                          " VALUES (%s, %s, 'test', 'y', 'a')", (V2, bad))



# ── the links belong to one AI card version ─────────────────────────────────

def _v3(dsn, pid, selected="{O1}"):
    """A third card version, the new latest, whose assessment selects `selected`."""
    v3 = "33333333-3333-3333-3333-333333333333"
    sql(dsn, pid, "INSERT INTO project.system (pid, number, name) VALUES (%s, 3, 'S')", (v3,))
    sql(dsn, pid, "INSERT INTO control_objectives.project VALUES ('a3', %s)", (v3,))
    sql(dsn, pid, "INSERT INTO control_objectives.objective_selection (project_id, objective_ids) VALUES ('a3', %s)",
        (selected,))
    return v3


def test_the_page_is_the_latest_versions_and_names_every_version(client, as_user, evidence_project):
    body = get(client, as_user, evidence_project).json()
    assert body["version"] == {"pid": V2, "number": 2}
    assert [v["number"] for v in body["versions"]] == [2, 1]
    assert body["read_only"] is False and body["carried_from"] is None


def test_links_are_saved_for_the_latest_version(client, as_user, evidence_project, dsn):
    put(client, as_user, evidence_project, [LB])
    assert sql(dsn, evidence_project["pid"], "SELECT system_id::text, objective_id FROM evidence.link") == [(V2, "O1")]


def test_an_older_version_reads_its_own_selection_and_cannot_change(client, as_user, evidence_project, dsn):
    put(client, as_user, evidence_project, [LB])
    older = client.get(f"/projects/{evidence_project['slug']}/evidence?version={V1}", headers=as_user(ALICE)).json()
    assert older["version"]["number"] == 1 and older["read_only"] is True
    assert [o["id"] for o in older["objectives"]] == ["O1", "O7"]
    assert older["links"] == []
    r = client.put(f"/projects/{evidence_project['slug']}/evidence/links", json={"links": [LB], "version": V1},
                   headers=as_user(ALICE))
    assert r.status_code == 409 and "version 1" in r.text


def test_a_version_not_in_the_project_is_404(client, as_user, evidence_project):
    r = client.get(f"/projects/{evidence_project['slug']}/evidence?version=99999999-9999-9999-9999-999999999999",
                   headers=as_user(ALICE))
    assert r.status_code == 404
    assert r.json()["detail"].startswith("no AI card version "), r.text


def test_a_new_version_is_offered_the_previous_links_still_in_its_matrix(client, as_user, evidence_project, dsn):
    put(client, as_user, evidence_project, [LB, GOV])                     # v2: O1 <- LangBiTe, O24 <- checklist
    v3 = _v3(dsn, evidence_project["pid"], "{O1}")
    body = get(client, as_user, evidence_project).json()
    assert body["version"]["number"] == 3 and body["carried_from"] == 2
    assert [(link["objective_id"], link["key"], link["carried"]) for link in body["links"]] == [
        ("O1", "aisc-plugin-langbite", True)]                  # O24 is not in v3's matrix
    # nothing is written until the assessor saves
    assert sql(dsn, evidence_project["pid"], "SELECT count(*) FROM evidence.link WHERE system_id = %s", (v3,)) == [(0,)]
    saved = put(client, as_user, evidence_project, [LB]).json()
    assert saved["carried_from"] is None and [link["carried"] for link in saved["links"]] == [False]
    assert sql(dsn, evidence_project["pid"], "SELECT count(*) FROM evidence.link WHERE system_id = %s", (v3,)) == [(1,)]
    # version 2 keeps its own
    assert sql(dsn, evidence_project["pid"], "SELECT count(*) FROM evidence.link WHERE system_id = %s", (V2,)) == [(2,)]


def _saved_events(pid):
    from tests.ledger.test_ledger_outbox import SUPERUSER_DSN, as_superuser

    if not SUPERUSER_DSN:
        pytest.skip("PLATFORM_TEST_SUPERUSER_URL is not set: ledger.outbox is read as the superuser")
    return as_superuser(pid, "SELECT item_id, card_version::text, details, content FROM ledger.outbox"
                             " WHERE action = 'evidence.links.saved' ORDER BY occurred_at")


def test_saving_links_records_what_changed(client, as_user, evidence_project, monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "record")
    assert put(client, as_user, evidence_project, [LB, GOV]).status_code == 200
    assert put(client, as_user, evidence_project, [LB]).status_code == 200
    got = _saved_events(evidence_project["pid"])
    assert [(i, c, d) for i, c, d, _ in got] == [
        (V2, V2, {"added": 2, "removed": 0, "carried": False}),
        (V2, V2, {"added": 0, "removed": 1, "carried": False})]
    assert got[1][3] == [["O1", "test", "aisc-plugin-langbite"]]


def test_unlinking_the_last_links_is_recorded_as_saved_not_rejected(client, as_user, evidence_project,
                                                                        monkeypatch):
    from platform_service.ledger import registry

    monkeypatch.setenv("LEDGER_MODE", "record")
    assert put(client, as_user, evidence_project, [LB]).status_code == 200
    assert put(client, as_user, evidence_project, []).status_code == 200
    got = _saved_events(evidence_project["pid"])
    assert got[-1][2] == {"added": 0, "removed": 1, "carried": False} and got[-1][3] == []
    event = {"action": "evidence.links.saved", "item_type": "evidence", "item_id": V2, "details": got[-1][2],
             "content": got[-1][3]}
    assert "content_required" not in registry.check(event, emitter="platform")


def test_a_save_that_takes_the_carried_links_says_so(client, as_user, evidence_project, dsn, monkeypatch):
    monkeypatch.setenv("LEDGER_MODE", "record")
    put(client, as_user, evidence_project, [LB, GOV])
    v3 = _v3(dsn, evidence_project["pid"], "{O1}")
    assert put(client, as_user, evidence_project, [LB]).status_code == 200
    assert _saved_events(evidence_project["pid"])[-1][:3] == (v3, v3, {"added": 1, "removed": 0, "carried": True})


def test_links_and_their_event_are_written_together_or_not_at_all(client, as_user, evidence_project, dsn,
                                                                     monkeypatch):
    from platform_service.ledger import outbox

    monkeypatch.setenv("LEDGER_MODE", "record")

    def broken(*args, **kwargs):
        raise RuntimeError("the event could not be written")

    monkeypatch.setattr(outbox, "emit_project", broken)
    with pytest.raises(RuntimeError):
        put(client, as_user, evidence_project, [LB])
    assert sql(dsn, evidence_project["pid"], "SELECT count(*) FROM evidence.link") == [(0,)]


def test_deleting_a_version_deletes_its_links(client, as_user, evidence_project, dsn):
    put(client, as_user, evidence_project, [LB])
    sql(dsn, evidence_project["pid"], "DELETE FROM control_objectives.project WHERE system_id = %s", (V2,))
    sql(dsn, evidence_project["pid"], "DELETE FROM project.system WHERE pid = %s", (V2,))
    assert sql(dsn, evidence_project["pid"], "SELECT count(*) FROM evidence.link") == [(0,)]


def test_template_0019_gives_every_link_its_version(evidence_project, dsn):
    from pathlib import Path

    folder = Path(evidence.__file__).resolve().parent.parent / "project-template"
    pid = evidence_project["pid"]
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


# ── step 4 test tiles: each test's engine name and its runs on the version shown ──

def _runs(dsn, pid, plugin, version, *statuses, by="package_name", evaluation_status="Done", component=None,
          when=None, local=None, helpers=()):
    """One plugin config of the engine plugin whose `by` column is `plugin`, then one evaluation of `version`
    per status running it once; each on the engine component `component` (an evaluation input named
    target) or with no target input, created at `when` (default now). `local`: the marker the worker
    stores on the model input of a run on a local model file; `helpers`: (role, model) of each helper
    model input, model None when the run's value names none (optionally a third item, the endpoint's name,
    default "<role> endpoint"). The evaluation plugins' pids, in order."""
    assert by in ("package_name", "name")
    plugin = sql(dsn, pid, f"SELECT id FROM engine.aisc_backend_plugin WHERE {by} = %s", (plugin,))[0][0]
    config = sql(dsn, pid, "INSERT INTO engine.aisc_backend_pluginconfig (plugin_id, name) VALUES (%s, 'c')"
                           " RETURNING id", (plugin,))[0][0]
    made = []
    for status in statuses:
        ev = sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluation (status, system_id, created_at)"
                           " VALUES (%s, %s, COALESCE(%s::timestamptz, now())) RETURNING id",
                 (evaluation_status, version, when))[0][0]
        ep = sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluationplugin (evaluation_id, plugin_config_id,"
                           " status) VALUES (%s, %s, %s) RETURNING id", (ev, config, status))[0][0]
        if component is not None:
            sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluationinput (evaluation_plugin_id, name, component_id)"
                          " VALUES (%s, 'target', %s)", (ep, component))
        if local is not None:
            sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluationinput (evaluation_plugin_id, name, value)"
                          " VALUES (%s, 'model', %s::jsonb)", (ep, json.dumps({"local_model": local})))
        for role, model, *endpoint in helpers:
            endpoint = endpoint[0] if endpoint else f"{role} endpoint"
            llm = sql(dsn, pid, "INSERT INTO engine.aisc_backend_aicomponent (id, pid, name)"
                                " SELECT coalesce(max(id), 0) + 1, gen_random_uuid(), %s"
                                " FROM engine.aisc_backend_aicomponent RETURNING id", (endpoint,))[0][0]
            sql(dsn, pid, "INSERT INTO engine.aisc_backend_evaluationinput (evaluation_plugin_id, name, component_id,"
                          " value) VALUES (%s, %s, %s, %s::jsonb)",
                (ep, f"helper:{role}", llm, json.dumps({"model": model} if model else {})))
        made.append(sql(dsn, pid, "SELECT pid::text FROM engine.aisc_backend_evaluationplugin WHERE id = %s",
                        (ep,))[0][0])
    return made


@pytest.fixture
def engine(evidence_project, dsn):
    pid = evidence_project["pid"]
    sql(dsn, pid, "INSERT INTO engine.aisc_backend_project (name, project_id) VALUES ('evd-workspace', %s)", (pid,))
    sql(dsn, pid, "UPDATE engine.aisc_backend_plugin SET name = 'LangBiTePlugin'"
                  " WHERE package_name = 'aisc-plugin-langbite'")
    sql(dsn, pid, "UPDATE engine.aisc_backend_plugin SET name = 'PromptfooPlugin'"
                  " WHERE package_name = 'aisc-plugin-promptfoo'")
    return evidence_project


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


def test_no_engine_tables_yet_reads_as_no_runs(client, as_user, evidence_project, dsn):
    """For every test and every engine plugin."""
    sql(dsn, evidence_project["pid"], "DROP TABLE engine.aisc_backend_evaluationplugin, engine.aisc_backend_evaluation,"
                                      " engine.aisc_backend_project")
    body = get(client, as_user, evidence_project).json()
    assert body["engine_workspace"] is None
    assert all(t["runs"] == {"executed": 0, "failed": 0, "running": 0} for t in body["tests"])
    assert body["plugins"] and all(p["runs"] == {"executed": 0, "failed": 0, "running": 0} for p in body["plugins"])


# ── step 4 test tiles per engine plugin: a package may ship several plugins ──────────
# data-monitor ships Data Drift and Data Anomaly. `tests` stays one entry per package (links, dimensions
# and the report key a test by its package); `plugins` is one entry per engine plugin, for the tiles.

def _two_plugin_package(dsn, pid, anomaly_enabled=True):
    sql(dsn, pid, "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name, enabled, name)"
                  " VALUES ('data-monitor', '0.4.0', 'Data Anomaly', %s, 'DataAnomalyPlugin'),"
                  "        ('data-monitor', '0.4.0', 'Data Drift', true, 'DataDriftPlugin')", (anomaly_enabled,))


def test_every_engine_plugin_is_listed_with_its_own_runs_even_when_two_share_a_package(client, as_user,
                                                                                       engine, dsn):
    pid = engine["pid"]
    _two_plugin_package(dsn, pid)
    _runs(dsn, pid, "DataDriftPlugin", V2, "Done", "Done", "Failed", by="name")
    _runs(dsn, pid, "DataAnomalyPlugin", V2, "Done", by="name")
    _runs(dsn, pid, "DataAnomalyPlugin", V1, "Done", by="name")                  # another card version
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


def test_tests_stays_one_entry_per_package(client, as_user, engine, dsn):
    _two_plugin_package(dsn, engine["pid"])
    keys = [t["key"] for t in get(client, as_user, engine).json()["tests"]]
    assert sorted(keys) == ["aisc-plugin-langbite", "aisc-plugin-promptfoo", "data-monitor"]


def test_a_disabled_plugin_says_so_on_its_own(client, as_user, engine, dsn):
    _two_plugin_package(dsn, engine["pid"], anomaly_enabled=False)
    plugins = {p["engine_name"]: p for p in get(client, as_user, engine).json()["plugins"]}
    assert plugins["DataAnomalyPlugin"]["stale"] == "disabled" and plugins["DataDriftPlugin"]["stale"] is None


def _upgraded_langbite(dsn, pid):
    """LangBiTe upgraded in the engine, as on a real project: the engine keeps the old version's row,
    disabled, next to the new one, since a run takes the lowest enabled version."""
    sql(dsn, pid, "UPDATE engine.aisc_backend_plugin SET version = '0.2.4', enabled = false"
                  " WHERE name = 'LangBiTePlugin'")
    sql(dsn, pid, "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name, enabled, name)"
                  " VALUES ('aisc-plugin-langbite', '0.2.6', 'LangBiTe', true, 'LangBiTePlugin')")


def test_an_upgraded_plugin_has_one_tile_with_every_versions_runs(client, as_user, engine, dsn):
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


def test_an_upgraded_test_is_not_disabled_whichever_row_comes_last(client, as_user, engine, dsn):
    _upgraded_langbite(dsn, engine["pid"])
    sql(dsn, engine["pid"], "UPDATE engine.aisc_backend_plugin SET id = id + 100 WHERE enabled = false")
    tests = {t["key"]: t for t in get(client, as_user, engine).json()["tests"]}
    assert tests["aisc-plugin-langbite"]["stale"] is None


def test_a_plugin_disabled_in_every_version_still_says_so(client, as_user, engine, dsn):
    _upgraded_langbite(dsn, engine["pid"])
    sql(dsn, engine["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = false WHERE name = 'LangBiTePlugin'")
    body = get(client, as_user, engine).json()
    tiles = [p for p in body["plugins"] if p["engine_name"] == "LangBiTePlugin"]
    assert len(tiles) == 1 and tiles[0]["stale"] == "disabled"
    assert {t["key"]: t for t in body["tests"]}["aisc-plugin-langbite"]["stale"] == "disabled"


# ── step 4 control tiles: each checklist's latest answers, as the controls app shows them ──

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


def test_a_checklist_never_answered_has_its_questions_and_no_submission(client, as_user, evidence_project, dsn):
    _questions(dsn, evidence_project["pid"], "ck1", 4)
    ck = {c["key"]: c for c in get(client, as_user, evidence_project).json()["controls"]}["ck1"]
    assert ck["questions"] == 4 and ck["submission"] is None


def test_a_checklist_shows_its_latest_version_score_and_completion(client, as_user, evidence_project, dsn):
    pid = evidence_project["pid"]
    _questions(dsn, pid, "ck1", 4)
    _submission(dsn, pid, "s1", "ck1", 1, "Closed", [(1, "x"), (1, "x"), (1, "x"), (1, "x")], age_s=60)
    # v2 continues v1: scores 5, 4 and a written answer without a score; the fourth question is open
    _submission(dsn, pid, "s2", "ck1", 2, "Draft", [(5, "x"), (4, None), (None, "only words")], previous="s1")
    ck = {c["key"]: c for c in get(client, as_user, evidence_project).json()["controls"]}["ck1"]
    # readiness as the controls app computes it: (mean - 1) / 4, rounded half up (4.5 -> 87.5 -> 88%)
    assert ck["submission"] == {"id": "s2", "version": 2, "status": "Draft", "readiness": 88, "answered": 3,
                                "questions": 4}
    assert ck["questions"] == 4


def test_an_archived_chain_is_not_shown_and_nothing_scored_has_no_readiness(client, as_user, evidence_project, dsn):
    pid = evidence_project["pid"]
    _questions(dsn, pid, "ck1", 2)
    _submission(dsn, pid, "old", "ck1", 3, "Closed", [(5, "x"), (5, "x")], archived=True)
    _submission(dsn, pid, "new", "ck1", 1, "Draft", [(None, " ")], age_s=30)
    ck = {c["key"]: c for c in get(client, as_user, evidence_project).json()["controls"]}["ck1"]
    assert ck["submission"] == {"id": "new", "version": 1, "status": "Draft", "readiness": None, "answered": 0,
                                "questions": 2}


def test_a_closed_submission_counts_over_the_questions_it_answered(client, as_user, evidence_project, dsn):
    """A closed submission keeps its answers to questions removed from the template since (their link to the
    question is gone): it is counted, as the controls app counts it, over today's questions and those."""
    pid = evidence_project["pid"]
    _questions(dsn, pid, "ck1", 2)
    _submission(dsn, pid, "s1", "ck1", 1, "Closed", [(5, "x")])
    sql(dsn, pid, "INSERT INTO controls.submission_answer (id, \"submissionId\", \"questionId\", answer, score)"
                  " VALUES ('s1-kept', 's1', NULL, 'kept', 3)")
    ck = {c["key"]: c for c in get(client, as_user, evidence_project).json()["controls"]}["ck1"]
    assert ck["questions"] == 2
    assert ck["submission"] == {"id": "s1", "version": 1, "status": "Closed", "readiness": 75, "answered": 2,
                                "questions": 3}


def test_a_deleted_checklist_has_no_questions_and_no_submission(client, as_user, evidence_project, dsn):
    put(client, as_user, evidence_project, [GOV])
    sql(dsn, evidence_project["pid"], "DELETE FROM controls.checklist WHERE id = 'ck1'")
    ck = {c["key"]: c for c in get(client, as_user, evidence_project).json()["controls"]}["ck1"]
    assert ck["stale"] == "deleted" and ck["questions"] is None and ck["submission"] is None


# ── results navigation ──────────────────────────────────────────────────────

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


def _targets(client, as_user, project, version=None):
    url = f"/projects/{project['slug']}/evidence" + (f"?version={version}" if version else "")
    return client.get(url, headers=as_user(ALICE)).json()["targets"]


def test_targets_are_listed_system_first_then_components_by_label(client, as_user, targets):
    got = _targets(client, as_user, targets)
    assert [(t["key"], t["kind"], t["component_kind"], t["label"], t["stale"]) for t in got] == [
        ("system", "system", None, "MCAS", False),
        (COMP, "component", "llm", "Explanation assistant", False),
        (GONE, "component", "model", "Old model", True),
    ]
    assert all(t["tools"] == [] for t in got)


def test_each_target_counts_its_tools_runs_on_the_version_shown(client, as_user, targets, dsn):
    pid = targets["pid"]
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", component=1, when="2026-09-30 08:00+00")
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Failed", component=1, when="2026-10-01 09:30+00")
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Running", component=1, when="2026-09-29 08:00+00")
    _runs(dsn, pid, "aisc-plugin-promptfoo", V2, "Done", component=1, when="2026-10-01 10:00+00")
    _runs(dsn, pid, "aisc-plugin-langbite", V1, "Done", component=1)          # another version
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", component=2)          # the stale component
    got = {t["key"]: t for t in _targets(client, as_user, targets)}
    counted = ("key", "label", "executed", "failed", "running", "last_run")
    assert [{k: tool[k] for k in counted} for tool in got[COMP]["tools"]] == [
        {"key": "aisc-plugin-langbite", "label": "LangBiTe", "executed": 1, "failed": 1, "running": 1,
         "last_run": "2026-10-01T09:30:00+00:00"},
        {"key": "aisc-plugin-promptfoo", "label": "Promptfoo", "executed": 1, "failed": 0, "running": 0,
         "last_run": "2026-10-01T10:00:00+00:00"},
    ]
    assert [t["key"] for t in got[GONE]["tools"]] == ["aisc-plugin-langbite"]
    assert got["system"]["tools"] == []
    older = {t["key"]: t for t in _targets(client, as_user, targets, V1)}
    assert [(t["key"], t["executed"]) for t in older[COMP]["tools"]] == [("aisc-plugin-langbite", 1)]


def test_runs_with_no_target_are_one_more_entry_last_only_when_there_are_some(client, as_user, targets, dsn):
    assert all(t["kind"] != "unassigned" for t in _targets(client, as_user, targets))
    _runs(dsn, targets["pid"], "aisc-plugin-langbite", V2, "Done")
    last = _targets(client, as_user, targets)[-1]
    assert (last["key"], last["kind"], last["label"]) == (None, "unassigned", "No target")
    assert [(t["key"], t["executed"]) for t in last["tools"]] == [("aisc-plugin-langbite", 1)]


def test_no_target_table_reads_as_no_targets(client, as_user, evidence_project, dsn):
    sql(dsn, evidence_project["pid"], "DROP TABLE engine.aisc_backend_evaluationinput")
    sql(dsn, evidence_project["pid"], "ALTER TABLE target.target RENAME TO target_gone")
    assert _targets(client, as_user, evidence_project) == []


# ── what each run assessed, how it was reached, and with which helper models ──────────

FINGERPRINT = "sha256:" + "ab" * 32
SHA = "0123456789abcdef" * 4


def _use(dsn, pid, run, connection="assistant-api", protocol="openai", fingerprint=FINGERPRINT):
    """The platform's record that the run `run` (its evaluation plugin's pid) reached `connection`."""
    with psycopg.connect(dsn) as conn:
        conn.execute("INSERT INTO core.run_pass_use (pass_hash, evaluation_plugin, pid, connection, protocol,"
                     " fingerprint) VALUES ('h', %s, %s, %s, %s, %s)", (run, pid, connection, protocol, fingerprint))


def _body(client, as_user, project):
    return client.get(f"/projects/{project['slug']}/evidence", headers=as_user(ALICE)).json()


def test_a_card_run_says_which_connection_reached_its_target(client, as_user, targets, dsn):
    pid = targets["pid"]
    run, = _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", component=1, when="2026-10-01 09:30+00")
    _use(dsn, pid, run)
    _use(dsn, targets["pid"], run, connection="assistant-api")                    # the same use again: one
    tool, = {t["key"]: t for t in _body(client, as_user, targets)["targets"]}[COMP]["tools"]
    reached = {"name": "assistant-api", "protocol": "openai", "protocol_name": "OpenAI-compatible",
               "fingerprint": FINGERPRINT}
    assert tool["runs"] == [{"run": run, "status": "Done", "created_at": "2026-10-01T09:30:00+00:00",
                             "assessed": {"family": "card", "label": "Explanation assistant",
                                          "connection": reached, "file": None},
                             "helpers": []}]
    assert tool["connections"] == [reached] and tool["helpers"] == []


def test_a_card_run_with_no_recorded_use_names_no_connection(client, as_user, targets, dsn):
    pid = targets["pid"]
    run, = _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", component=1)
    other = client.post("/projects", json={"name": "elsewhere"}, headers=as_user(ALICE)).json()
    _use(dsn, other["pid"], run)                                                # another project's use
    tool, = {t["key"]: t for t in _body(client, as_user, targets)["targets"]}[COMP]["tools"]
    assert tool["runs"][0]["assessed"]["connection"] is None and tool["connections"] == []


def test_a_tool_lists_each_connection_its_runs_reached_once(client, as_user, targets, dsn):
    pid = targets["pid"]
    first, second, third = _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", "Done", "Done", component=1)
    _use(dsn, pid, first)
    _use(dsn, pid, second)
    _use(dsn, pid, third, connection="assistant-a2a", protocol="a2a", fingerprint="sha256:" + "cd" * 32)
    tool, = {t["key"]: t for t in _body(client, as_user, targets)["targets"]}[COMP]["tools"]
    assert [(c["name"], c["protocol_name"]) for c in tool["connections"]] == [
        ("assistant-api", "OpenAI-compatible"), ("assistant-a2a", "A2A agent")]


def test_each_run_lists_its_helper_models_and_the_tool_each_one_once(client, as_user, targets, dsn):
    pid = targets["pid"]
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", component=1,
          helpers=(("judge", "gpt-4o-mini"), ("attacker", "llama-3")))
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", component=1, helpers=(("judge", "gpt-4o-mini"),))
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", component=1, helpers=(("grader", None),))
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", component=1, helpers=(("embedder", None, None),))
    tool, = {t["key"]: t for t in _body(client, as_user, targets)["targets"]}[COMP]["tools"]
    assert [r["helpers"] for r in tool["runs"]] == [                    # newest first
        [{"role": "embedder", "model": "unnamed endpoint"}],            # neither a model nor an endpoint name
        [{"role": "grader", "model": "grader endpoint"}],               # no model picked: the endpoint's name
        [{"role": "judge", "model": "gpt-4o-mini"}],
        [{"role": "attacker", "model": "llama-3"}, {"role": "judge", "model": "gpt-4o-mini"}],
    ]
    assert tool["helpers"] == [{"role": "attacker", "model": "llama-3"},
                               {"role": "embedder", "model": "unnamed endpoint"},
                               {"role": "grader", "model": "grader endpoint"},
                               {"role": "judge", "model": "gpt-4o-mini"}]


def test_a_local_run_is_listed_apart_and_never_counted_with_the_ai_cards(client, as_user, targets, dsn):
    pid = targets["pid"]
    _runs(dsn, pid, "aisc-plugin-langbite", V2, "Done", local={"file": "scoring.onnx", "sha256": SHA},
          when="2026-10-02 08:00+00", helpers=(("judge", "gpt-4o-mini"),))
    # marked local, whatever else it has: a target input too
    _runs(dsn, pid, "aisc-plugin-promptfoo", V2, "Failed", component=1,
          local={"file": "other.onnx", "sha256": SHA}, when="2026-10-03 08:00+00")
    body = _body(client, as_user, targets)
    assert all(t["tools"] == [] for t in body["targets"]) and all(t["kind"] != "unassigned" for t in body["targets"])
    assert all(t["runs"] == {"executed": 0, "failed": 0, "running": 0} for t in body["tests"])
    assert all(p["runs"] == {"executed": 0, "failed": 0, "running": 0} for p in body["plugins"])
    assert [{k: r[k] for k in ("key", "label", "status", "created_at", "assessed", "helpers")}
            for r in body["local_runs"]] == [
        {"key": "aisc-plugin-promptfoo", "label": "Promptfoo", "status": "Failed",
         "created_at": "2026-10-03T08:00:00+00:00",
         "assessed": {"family": "local", "label": "other.onnx", "connection": None,
                      "file": {"name": "other.onnx", "sha256": SHA}}, "helpers": []},
        {"key": "aisc-plugin-langbite", "label": "LangBiTe", "status": "Done",
         "created_at": "2026-10-02T08:00:00+00:00",
         "assessed": {"family": "local", "label": "scoring.onnx", "connection": None,
                      "file": {"name": "scoring.onnx", "sha256": SHA}},
         "helpers": [{"role": "judge", "model": "gpt-4o-mini"}]},
    ]


def test_local_runs_are_listed_even_before_the_project_has_targets(client, as_user, engine, dsn):
    _runs(dsn, engine["pid"], "aisc-plugin-langbite", V2, "Done", local={"file": "scoring.onnx", "sha256": SHA})
    sql(dsn, engine["pid"], "DELETE FROM target.target")
    body = _body(client, as_user, engine)
    assert body["targets"] == [] and [r["key"] for r in body["local_runs"]] == ["aisc-plugin-langbite"]


def test_runs_before_targets_stay_no_target_and_name_nothing_they_assessed(client, as_user, targets, dsn):
    run, = _runs(dsn, targets["pid"], "aisc-plugin-langbite", V2, "Done")
    last = _body(client, as_user, targets)["targets"][-1]
    assert (last["key"], last["label"]) == (None, "No target")
    assert [r["assessed"] for r in last["tools"][0]["runs"]] == [None]
    assert last["tools"][0]["connections"] == [] and _body(client, as_user, targets)["local_runs"] == []


def test_no_engine_tables_yet_reads_as_no_local_runs(client, as_user, evidence_project, dsn):
    sql(dsn, evidence_project["pid"], "DROP TABLE engine.aisc_backend_evaluationinput")
    assert _body(client, as_user, evidence_project)["local_runs"] == []


def test_a_failed_local_run_marked_at_its_creation_is_local_without_a_hash(client, as_user, targets, dsn):
    """The engine marks a local run when it creates it, with the file's name; the worker adds the hash once
    the run reads the file. A run that failed before has the name alone, and is still local."""
    _runs(dsn, targets["pid"], "aisc-plugin-langbite", V2, "Failed", local={"file": "scoring.onnx"})
    body = _body(client, as_user, targets)
    assert all(t["tools"] == [] for t in body["targets"])
    assert all(p["runs"] == {"executed": 0, "failed": 0, "running": 0} for p in body["plugins"])
    assert [(r["status"], r["assessed"]) for r in body["local_runs"]] == [
        ("Failed", {"family": "local", "label": "scoring.onnx", "connection": None,
                    "file": {"name": "scoring.onnx", "sha256": None}})]


def test_local_runs_are_listed_whatever_card_version_they_were_made_on(client, as_user, engine, dsn):
    pid = engine["pid"]
    _runs(dsn, pid, "aisc-plugin-langbite", V1, "Done", local={"file": "old.onnx", "sha256": SHA},
          when="2026-10-01 08:00+00")
    _runs(dsn, pid, "aisc-plugin-langbite", None, "Done", local={"file": "unstamped.onnx", "sha256": SHA},
          when="2026-10-02 08:00+00")
    for version in (V1, V2):
        body = client.get(f"/projects/{engine['slug']}/evidence?version={version}", headers=as_user(ALICE)).json()
        assert [r["assessed"]["label"] for r in body["local_runs"]] == ["unstamped.onnx", "old.onnx"]


def test_a_project_with_no_ai_card_version_lists_its_local_runs(client, as_user, make_project, dsn):
    p = make_project()
    sql(dsn, p["pid"], MODULE_TABLES)
    sql(dsn, p["pid"], "INSERT INTO engine.aisc_backend_plugin (package_name, version, display_name, enabled)"
                       " VALUES ('aisc-plugin-performance', '1.0', 'Performance', true)")
    _runs(dsn, p["pid"], "aisc-plugin-performance", None, "Done", local={"file": "scoring.onnx", "sha256": SHA})
    body = _body(client, as_user, p)
    assert body["version"] is None
    assert [(r["label"], r["assessed"]["label"]) for r in body["local_runs"]] == [("Performance", "scoring.onnx")]
