"""A fresh volume, and init files that survive the drop step (01-specs.md I1.3, I1.4, I2.8, I16.3, I16.4).

Throwaway postgres:14-alpine only (scripts/tests/isolation_bed.py), never the host's 5432.

    uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_fresh_volume.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess

import pytest

import isolation_bed as ib
from conftest import ROOT

PLATFORM_DB_SQL = ROOT / "init/platform-db.sql"
PROJECT_DATABASES_SQL = ROOT / "init/project-databases.sql"
MODULE_ROLES = ["qualification_rw", "control_objectives_rw", "controls_rw", "engine_rw", "report_composer_rw",
                "catalogue_rw"]


# ── I2.8 static: what platform-db.sql no longer makes, and what it makes ──────


def _sql(path):
    # comments out, so a sentence that names a statement does not count as the statement
    return re.sub(r"--[^\n]*", "", path.read_text())


def test_i2_8_platform_db_sql_no_longer_creates_core_system():
    assert not re.search(r"CREATE TABLE\s+(IF NOT EXISTS\s+)?core\.system\b", _sql(PLATFORM_DB_SQL), re.I), \
        "I2.8: init/platform-db.sql still creates core.system"


@pytest.mark.parametrize("schema", ["qualification", "control_objectives", "engine"])
def test_i2_8_platform_db_sql_no_longer_creates_the_module_schemas(schema):
    text = _sql(PLATFORM_DB_SQL)
    assert not re.search(rf"CREATE SCHEMA\s+(IF NOT EXISTS\s+)?{schema}\b", text, re.I), \
        f"I2.8: init/platform-db.sql still creates schema {schema}"
    assert not re.search(rf"'{schema}',\s*'{schema}_rw'", text), \
        f"I2.8: init/platform-db.sql still grants the {schema} module schema"


def test_i2_8_platform_db_sql_gives_dashboard_ro_no_default_privileges():
    assert not re.search(r"DEFAULT PRIVILEGES[^;]*dashboard_ro", _sql(PLATFORM_DB_SQL), re.I | re.S), \
        "I2.8: init/platform-db.sql still gives dashboard_ro default privileges"


def test_i2_8_platform_db_sql_sets_no_module_search_path():
    text = _sql(PLATFORM_DB_SQL)
    assert "IN DATABASE platform SET search_path = %I, core" not in text, \
        "I2.8: init/platform-db.sql still sets module search_paths"
    assert not re.search(r"dashboard_ro\s+IN DATABASE platform SET search_path[^;]*qualification", text), \
        "I2.8: dashboard_ro's platform search_path still names module schemas"


@pytest.mark.parametrize("schema,owner", [("report_library", "report_composer_rw")])
def test_i2_8_platform_db_sql_creates_the_report_library(schema, owner):
    """D4. There is no form library (forms are per project since the user's decision of 2026-09-25: no form library in platform)."""
    text = _sql(PLATFORM_DB_SQL)
    assert re.search(rf"CREATE SCHEMA\s+(IF NOT EXISTS\s+)?{schema}\b", text, re.I), \
        f"I2.8, D4: init/platform-db.sql does not create {schema}"
    assert re.search(rf"{schema}[^;]*{owner}|AUTHORIZATION\s+{owner}", text, re.S), \
        f"I2.8: {schema} is not owned by {owner}"


# ── I2.8 behaviour: project-databases.sql keeps running after the drop ────────


@pytest.fixture(scope="module")
def old_volume():
    """Init files and platform migrations as today, no project."""
    b = ib.build("initdrop", projects=(), modules=False)
    yield b
    b.stop()


def test_i2_8_project_databases_sql_runs_after_core_system_and_module_schemas_are_dropped(old_volume):
    """I2.8, I15.2: after stage 7 (DROP SCHEMA ... CASCADE; DROP TABLE core.system CASCADE) the file runs on
    every start of postgres-setup and exits 0."""
    b = old_volume
    r = b.psql("platform", "DROP SCHEMA IF EXISTS qualification, control_objectives, engine, report_composer CASCADE;"
                           "DROP TABLE IF EXISTS core.system CASCADE;"
                           "DROP FUNCTION IF EXISTS core.system_only_latest_changes();")
    assert r.returncode == 0, r.stderr
    again = b.psql("platform", PROJECT_DATABASES_SQL.read_text())
    assert again.returncode == 0, "I2.8: init/project-databases.sql fails once core.system is gone: " + \
        again.stderr.strip()[-300:]


# ── fresh volume: new init files, migrations, POST /projects ───────────────────


def _post_project(bed) -> dict:
    code = ("import json; from fastapi.testclient import TestClient; from platform_service.app import app\n"
            "c = TestClient(app); r = c.post('/projects', json={'name': 'fresh volume probe'})\n"
            "print(json.dumps({'status': r.status_code, 'body': r.json() if r.content else None}))\n")
    env = {**os.environ, "PLATFORM_DATABASE_URL": bed.dsn("platform_rw", "platform"),
           "PLATFORM_TEST_DATABASE_URL": bed.dsn("platform_rw", "platform"), "AUTH_ENABLED": "false",
           "DASHBOARD_BRIDGE_URL": "", "AISC_BRIDGE_TOKEN": "",
           "PYTHONPATH": f"{ROOT / 'platform'}:{ROOT / 'shared/identity'}"}
    r = subprocess.run(["uv", "run", "--quiet", "--extra", "dev", "python", "-c", code], cwd=ROOT / "platform",
                       env=env, capture_output=True, text=True, timeout=300)
    lines = r.stdout.strip().splitlines()
    try:
        return json.loads(lines[-1])
    except (IndexError, json.JSONDecodeError):
        return {"status": None, "exit": r.returncode,
                "error": (r.stderr or r.stdout).replace(bed.t.password, "***")[-500:]}


@pytest.fixture(scope="module")
def fresh():
    b = ib.build("fresh", projects=(), modules=False)
    try:
        created = _post_project(b)
        if created.get("status") == 201:
            b.projects.append(created["body"]["pid"])
            ib.migrate_modules(b)
        else:
            b.problems["post-projects"] = f"I16.4: POST /projects on a fresh volume gave {created}"
        yield b
    finally:
        b.stop()


def test_i16_4_init_files_and_migrations_apply_on_a_fresh_volume(fresh):
    """I2.8, I16.4: every init file and platform migration applies on an empty cluster."""
    fresh.require("init", "init-project-databases", "init-inspector-role", "init-report-roles", "platform-migrations")


def test_i1_3_platform_has_exactly_the_shared_schemas_on_a_fresh_volume(fresh):
    """I1.3, I16.2: `platform` holds core, catalogue, report_library and an empty public (forms are per project since the user's decision of 2026-09-25: no form library in platform)."""
    fresh.require("init")
    schemas = {r["nspname"] for r in fresh.rows("platform", """
        SELECT nspname FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname <> 'information_schema'""")}
    assert schemas == {"core", "catalogue", "report_library", "public"}, f"I1.3: {sorted(schemas)}"
    core = {r["relname"] for r in fresh.rows("platform", """
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'core' AND c.relkind = 'r'""")}
    assert core == {"project", "project_member", "schema_migration"}, f"I1.3, I16.2: core has {sorted(core)}"


@pytest.mark.parametrize("schema,owner", [("report_library", "report_composer_rw")])
def test_i1_4_library_schemas_are_owned_by_their_module(fresh, schema, owner):
    fresh.require("init")
    got = fresh.scalar("platform", f"SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = '{schema}'")
    assert got == owner, f"I1.4: platform schema {schema} owner {got!r}"


def _table_privs(bed, role):
    return {(r["rel"], r["priv"]) for r in bed.rows("platform", f"""
        SELECT n.nspname || '.' || c.relname AS rel, p.priv
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
               unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) AS p(priv)
         WHERE c.relkind IN ('r', 'p', 'v') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
           AND pg_get_userbyid(c.relowner) <> '{role}'
           AND has_table_privilege('{role}', c.oid, p.priv)""")}


@pytest.mark.parametrize("role", MODULE_ROLES)
def test_i1_4_a_module_role_reads_only_core_project_and_members_in_platform(fresh, role):
    """I1.4: a module role's only table privileges in `platform` (outside what it owns) are SELECT on
    core.project and core.project_member."""
    fresh.require("init", "platform-migrations")
    got = _table_privs(fresh, role)
    want = {("core.project", "SELECT"), ("core.project_member", "SELECT")}
    assert got == want, f"I1.4: {role} has {sorted(got - want)} beyond, lacks {sorted(want - got)}"


@pytest.mark.parametrize("role,want", [
    ("dashboard_ro", {("core.project_member", "SELECT")}),
    ("report_ro", {("core.project", "SELECT")}),
])
def test_i1_4_readers_in_platform(fresh, role, want):
    """I1.4, I10.2, I10.3: dashboard_ro only SELECT core.project_member; report_ro only SELECT core.project."""
    fresh.require("init", "init-report-roles", "platform-migrations")
    got = _table_privs(fresh, role)
    assert got == want, f"I1.4: {role} has {sorted(got)}"


def test_i16_4_post_projects_on_a_fresh_volume_yields_a_complete_project_database(fresh):
    """I16.3, I16.4: the project made through the API has template 0001..0010, project.system, and every
    module's migration tracker."""
    fresh.require("post-projects", "templates", "project_system", "qualification", "control_objectives",
                  "engine", "report_composer", "controls")
    db = ib.project_db(fresh.projects[0])
    names = [r["name"] for r in fresh.rows(db, "SELECT name FROM provision.template_migration ORDER BY 1")]
    assert names == ib.TEMPLATES
    for tracker in ib.TRACKERS.values():
        assert fresh.exists(db, tracker), f"I16.3: {db} lacks {tracker}"


def test_no_form_library_on_a_fresh_volume(fresh):
    """Forms are per project since the user's decision of 2026-09-25: neither the init files nor the migrations make form_library."""
    fresh.require("init")
    assert fresh.scalar("platform", "SELECT to_regnamespace('form_library') IS NULL") == "t", "form_library exists"
    assert "form_library" not in _sql(PLATFORM_DB_SQL), "init/platform-db.sql still names form_library"
