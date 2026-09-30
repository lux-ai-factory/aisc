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
GRANT SELECT ON control_objectives.project, control_objectives.objective_selection,
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
        {"id": "R1.1", "sub_requirement_label": "Risk management system"},
        {"id": "R6.1", "sub_requirement_label": "Human oversight"}]))
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
    v1 selected R1.1 and R2.3, v2 (the latest) selects R1.1 and R6.1; LangBiTe and Promptfoo are
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
                  " ('a1', '{R1.1,R2.3}'), ('a2', '{R1.1,R6.1}')")
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


LB = {"objective_id": "R1.1", "kind": "test", "key": "aisc-plugin-langbite"}
GOV = {"objective_id": "R6.1", "kind": "control", "key": "ck1"}


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
                                 " VALUES ('R1.1', 'model', 'x', 'a')")


# ── what the page lists ─────────────────────────────────────────────────────

def test_the_page_lists_the_latest_selection_the_plugins_and_the_checklists(client, as_user, project):
    body = get(client, as_user, project).json()
    assert [(o["id"], o["stale"]) for o in body["objectives"]] == [("R1.1", None), ("R6.1", None)]
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
        ("R1.1", "Risk management system"), ("R6.1", "Human oversight")]


def test_a_catalogue_that_is_down_leaves_the_names_empty(client, as_user, project, catalogue, monkeypatch):
    monkeypatch.setenv("CONTROL_OBJECTIVES_URL", "http://127.0.0.1:9")
    evidence.forget_titles()
    body = get(client, as_user, project)
    assert body.status_code == 200 and [o["title"] for o in body.json()["objectives"]] == ["", ""]


# ── linking (many to many) ──────────────────────────────────────────────────

def test_an_editor_links_tests_and_controls_to_objectives(client, as_user, project, dsn):
    both = {"objective_id": "R6.1", "kind": "test", "key": "aisc-plugin-langbite"}
    r = put(client, as_user, project, [LB, GOV, both], BOB)
    assert r.status_code == 200, r.text
    assert sorted((l["objective_id"], l["kind"], l["key"]) for l in r.json()["links"]) == [
        ("R1.1", "test", "aisc-plugin-langbite"), ("R6.1", "control", "ck1"), ("R6.1", "test", "aisc-plugin-langbite")]
    assert sql(dsn, project["pid"], "SELECT count(*) FROM evidence.link") == [(3,)]
    assert sql(dsn, project["pid"], "SELECT DISTINCT created_by FROM evidence.link") == [(BOB,)]


def test_saving_replaces_the_links_and_keeps_who_made_the_old_ones(client, as_user, project, dsn):
    put(client, as_user, project, [LB, GOV], BOB)
    r = put(client, as_user, project, [LB], ALICE)
    assert [(l["objective_id"], l["key"]) for l in r.json()["links"]] == [("R1.1", "aisc-plugin-langbite")]
    assert sql(dsn, project["pid"], "SELECT created_by FROM evidence.link") == [(BOB,)]


@pytest.mark.parametrize("link, why", [
    ({"objective_id": "R2.3", "kind": "test", "key": "aisc-plugin-langbite"}, "R2.3 is not selected"),
    ({"objective_id": "R1.1", "kind": "test", "key": "aisc-plugin-promptfoo"}, "disabled"),
    ({"objective_id": "R1.1", "kind": "test", "key": "aisc-plugin-nothing"}, "not installed"),
    ({"objective_id": "R1.1", "kind": "control", "key": "ck9"}, "not installed"),
    ({"objective_id": "R1.1", "kind": "model", "key": "ck1"}, "kind"),
])
def test_a_new_link_to_something_not_there_is_refused(client, as_user, project, link, why, dsn):
    r = put(client, as_user, project, [LB, link])
    assert r.status_code == 422 and why in r.text, r.text
    assert sql(dsn, project["pid"], "SELECT count(*) FROM evidence.link") == [(0,)]


# ── stale (D7) ──────────────────────────────────────────────────────────────

def test_links_that_went_stale_are_kept_and_shown_with_their_reason(client, as_user, project, dsn):
    promptfoo_on_r6 = {"objective_id": "R6.1", "kind": "test", "key": "aisc-plugin-promptfoo"}
    sql(dsn, project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = true")
    put(client, as_user, project, [LB, GOV, promptfoo_on_r6])
    # step 2 unselects R6.1, the engine disables Promptfoo, the checklist is deleted
    sql(dsn, project["pid"], "UPDATE control_objectives.objective_selection SET objective_ids = '{R1.1}'"
                             " WHERE project_id = 'a2'")
    sql(dsn, project["pid"], "UPDATE engine.aisc_backend_plugin SET enabled = false"
                             " WHERE package_name = 'aisc-plugin-promptfoo'")
    sql(dsn, project["pid"], "DELETE FROM controls.checklist")
    body = get(client, as_user, project).json()
    assert [(o["id"], o["stale"]) for o in body["objectives"]] == [("R1.1", None), ("R6.1", "not selected")]
    assert [(c["key"], c["label"], c["stale"]) for c in body["controls"]] == [("ck1", "ck1", "deleted")]
    stale = {(l["objective_id"], l["key"]): l["stale"] for l in body["links"]}
    assert stale == {("R1.1", "aisc-plugin-langbite"): None, ("R6.1", "ck1"): "not selected",
                     ("R6.1", "aisc-plugin-promptfoo"): "not selected"}
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
