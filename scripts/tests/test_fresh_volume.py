"""A fresh volume, and init files that still run once the old shared schemas are dropped.

Throwaway postgres:15-alpine only (scripts/tests/isolation_bed.py), never the host's 5432.

    uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_fresh_volume.py
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys

import pytest

import isolation_bed as ib
from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts"))
from db_consistency import checks  # noqa: E402

PLATFORM_DB_SQL = ROOT / "init/platform-db.sql"
PROJECT_DATABASES_SQL = ROOT / "init/project-databases.sql"
MODULE_ROLES = ["qualification_rw", "control_objectives_rw", "controls_rw", "engine_rw", "report_composer_rw",
                "catalogue_rw"]


# static: what platform-db.sql does not set


def _sql(path):
    # comments out, so a sentence that names a statement does not count as the statement
    return re.sub(r"--[^\n]*", "", path.read_text())


def test_platform_db_sql_gives_dashboard_ro_no_default_privileges():
    assert not re.search(r"DEFAULT PRIVILEGES[^;]*dashboard_ro", _sql(PLATFORM_DB_SQL), re.I | re.S), \
        "init/platform-db.sql still gives dashboard_ro default privileges"


def test_platform_db_sql_sets_no_module_search_path():
    text = _sql(PLATFORM_DB_SQL)
    assert "IN DATABASE platform SET search_path = %I, core" not in text, \
        "init/platform-db.sql still sets module search_paths"
    assert not re.search(r"dashboard_ro\s+IN DATABASE platform SET search_path[^;]*qualification", text), \
        "dashboard_ro's platform search_path still names module schemas"


# behaviour: project-databases.sql keeps running after the drop


@pytest.fixture(scope="module")
def old_volume():
    """Init files and platform migrations, no project."""
    b = ib.build("initdrop", projects=(), modules=False)
    yield b
    b.stop()


def test_project_databases_sql_runs_after_core_system_and_module_schemas_are_dropped(old_volume):
    """Once the old shared schemas and core.system are dropped (DROP SCHEMA ... CASCADE; DROP TABLE
    core.system CASCADE), the file still runs on every start of postgres-setup and exits 0."""
    b = old_volume
    r = b.psql("platform", "DROP SCHEMA IF EXISTS qualification, control_objectives, engine, report_composer CASCADE;"
                           "DROP TABLE IF EXISTS core.system CASCADE;"
                           "DROP FUNCTION IF EXISTS core.system_only_latest_changes();")
    assert r.returncode == 0, r.stderr
    again = b.psql("platform", PROJECT_DATABASES_SQL.read_text())
    assert again.returncode == 0, "init/project-databases.sql fails once core.system is gone: " + \
        again.stderr.strip()[-300:]


def test_an_older_volume_loses_the_unused_platform_schemas_and_the_catalogue_login(old_volume):
    """An install made before keeps the schemas catalogue and report_library and a catalogue_rw that logs in;
    the next start of postgres-setup drops both schemas and the login."""
    b = old_volume
    r = b.psql("platform", "CREATE SCHEMA IF NOT EXISTS catalogue AUTHORIZATION catalogue_rw;"
                           "CREATE SCHEMA IF NOT EXISTS report_library AUTHORIZATION report_composer_rw;"
                           "CREATE TABLE IF NOT EXISTS report_library.preset (id int);"
                           "ALTER ROLE catalogue_rw LOGIN PASSWORD 'catalogue_rw';")
    assert r.returncode == 0, r.stderr
    again = b.psql("platform", PROJECT_DATABASES_SQL.read_text())
    assert again.returncode == 0, again.stderr.strip()[-300:]
    left = b.rows("platform", "SELECT nspname FROM pg_namespace WHERE nspname IN ('catalogue', 'report_library')")
    assert left == []
    assert b.rows("platform", "SELECT rolcanlogin, rolpassword IS NULL AS no_password FROM pg_authid"
                              " WHERE rolname = 'catalogue_rw'") == [{"rolcanlogin": False, "no_password": True}]


# fresh volume: init files, migrations, POST /projects


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
            b.problems["post-projects"] = f"POST /projects on a fresh volume gave {created}"
        yield b
    finally:
        b.stop()


def test_init_files_and_migrations_apply_on_a_fresh_volume(fresh):
    """Every init file and platform migration applies on an empty cluster."""
    fresh.require("init", "init-project-databases", "init-inspector-role", "init-report-roles", "platform-migrations")


def test_platform_has_exactly_the_shared_schemas_on_a_fresh_volume(fresh):
    """`platform` holds core, the ledger's own schema and an empty public (forms are per project, so there is
    no form library; the catalogue is per project too, and there is no report library); core holds the projects, their members, the migration
    history, the platform's ledger outbox, the run passes it issued and the connections those runs reached."""
    fresh.require("init")
    schemas = {r["nspname"] for r in fresh.rows("platform", """
        SELECT nspname FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname <> 'information_schema'""")}
    assert schemas == {"core", "ledger", "public"}, f"platform schemas: {sorted(schemas)}"
    core = {r["relname"] for r in fresh.rows("platform", """
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'core' AND c.relkind = 'r'""")}
    assert core == {"project", "project_member", "schema_migration", "outbox", "run_pass", "run_pass_use"}, f"core has {sorted(core)}"



def test_the_consistency_check_knows_every_core_table_the_migrations_make(fresh):
    """scripts/db_consistency lists exactly the core tables a fresh platform database has, so a new core
    table fails here instead of warning on every healthy install."""
    fresh.require("init", "platform-migrations")
    core = {r["relname"] for r in fresh.rows("platform", """
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'core' AND c.relkind IN ('r', 'p')""")}
    assert core == checks.CORE_TABLES, f"core has {sorted(core)}, the check lists {sorted(checks.CORE_TABLES)}"

def test_the_catalogue_role_cannot_log_in_on_a_fresh_volume(fresh):
    """catalogue_rw is kept only because the first platform migrations grant to it; nothing logs in as it."""
    fresh.require("init")
    assert fresh.rows("platform", "SELECT rolcanlogin FROM pg_roles WHERE rolname = 'catalogue_rw'") == \
        [{"rolcanlogin": False}]


def _table_privs(bed, role):
    return {(r["rel"], r["priv"]) for r in bed.rows("platform", f"""
        SELECT n.nspname || '.' || c.relname AS rel, p.priv
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
               unnest(ARRAY['SELECT','INSERT','UPDATE','DELETE','TRUNCATE','REFERENCES','TRIGGER']) AS p(priv)
         WHERE c.relkind IN ('r', 'p', 'v') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
           AND pg_get_userbyid(c.relowner) <> '{role}'
           AND has_table_privilege('{role}', c.oid, p.priv)""")}


@pytest.mark.parametrize("role", MODULE_ROLES)
def test_a_module_role_reads_only_core_project_and_members_in_platform(fresh, role):
    """A module role's only table privileges in `platform` (outside what it owns) are SELECT on
    core.project and core.project_member."""
    fresh.require("init", "platform-migrations")
    got = _table_privs(fresh, role)
    want = {("core.project", "SELECT"), ("core.project_member", "SELECT")}
    assert got == want, f"{role} has {sorted(got - want)} beyond, lacks {sorted(want - got)}"


@pytest.mark.parametrize("role,want", [
    ("dashboard_ro", {("core.project_member", "SELECT")}),
    ("report_ro", {("core.project", "SELECT")}),
])
def test_readers_in_platform(fresh, role, want):
    """dashboard_ro may only SELECT core.project_member; report_ro may only SELECT core.project."""
    fresh.require("init", "init-report-roles", "platform-migrations")
    got = _table_privs(fresh, role)
    assert got == want, f"{role} has {sorted(got)}"


def test_post_projects_on_a_fresh_volume_yields_a_complete_project_database(fresh):
    """The project made through the API has template migrations 0001 to 0010, project.system, and every
    module's migration tracker."""
    fresh.require("post-projects", "templates", "project_system", "qualification", "control_objectives",
                  "engine", "report_composer", "controls")
    db = ib.project_db(fresh.projects[0])
    names = [r["name"] for r in fresh.rows(db, "SELECT name FROM provision.template_migration ORDER BY 1")]
    assert names == ib.TEMPLATES
    for tracker in ib.TRACKERS.values():
        assert fresh.exists(db, tracker), f"{db} lacks {tracker}"


def test_no_form_library_on_a_fresh_volume(fresh):
    """Forms are per project: neither the init files nor the migrations make form_library."""
    fresh.require("init")
    assert fresh.scalar("platform", "SELECT to_regnamespace('form_library') IS NULL") == "t", "form_library exists"
    assert "form_library" not in _sql(PLATFORM_DB_SQL), "init/platform-db.sql still names form_library"
