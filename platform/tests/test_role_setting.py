"""The one door through which the template sets a module role's search_path.

platform_rw applies the template but cannot run
`ALTER ROLE <another role> IN DATABASE ... SET` on PG14, so templates 0007..0010 call
aisc_setup.apply_role_setting, a SECURITY DEFINER function owned by the superuser that
init/project-databases.sql puts into template1. It must run that one statement for the four
module roles, each with its own schema, in the database it is called in, and refuse anything
else; only platform_rw may call it. `projectdb.install_setup_function` puts it into a database
made before template1 had it, and `projectdb.provision_as` provisions as the superuser the way the
platform would (both for the isolate tool).

Needs PLATFORM_TEST_DATABASE_URL (platform_rw) and PLATFORM_TEST_SUPERUSER_URL on a throwaway.
"""
from __future__ import annotations

import os
import time
import uuid

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import needs_database
from tests.core_scratch import needs_superuser

ALICE = "00000000-0000-0000-0000-00000000a11c"
PAIRS = {"qualification_rw": "qualification", "control_objectives_rw": "control_objectives",
         "engine_rw": "engine", "report_composer_rw": "report_composer"}


def _su() -> str:
    return os.environ["PLATFORM_TEST_SUPERUSER_URL"]


def _connect(dsn: str, dbname: str, role: str | None = None) -> psycopg.Connection:
    base = dsn if role is None else make_conninfo(dsn, user=role, password=role)
    return psycopg.connect(make_conninfo(base, dbname=dbname), autocommit=True)


def _wait_until_closed(dsn: str, db: str, role: str) -> None:
    """A closed session's backend may still be exiting; the suite's cleanup drops the database
    WITH (FORCE) as platform_rw, which may not end another role's session. Wait for it (5 s)."""
    deadline = time.monotonic() + 5
    with psycopg.connect(dsn, autocommit=True) as conn:
        while time.monotonic() < deadline and conn.execute(
                "select count(*) from pg_stat_activity where datname = %s and usename = %s",
                (db, role)).fetchone()[0]:
            time.sleep(0.1)


@pytest.fixture
def project(client, as_user, unique):
    response = client.post("/projects", json={"name": unique("setting")}, headers=as_user(ALICE))
    assert response.status_code == 201, response.text
    return response.json()


@needs_database
@pytest.mark.parametrize("statement", [
    # a module role with another module's schema
    "ALTER ROLE engine_rw IN DATABASE {db} SET search_path = qualification",
    # a role that is not one of the four
    "ALTER ROLE platform_rw IN DATABASE {db} SET search_path = engine",
    "ALTER ROLE dashboard_ro IN DATABASE {db} SET search_path = engine",
    # another database than the one it is called in
    "ALTER ROLE engine_rw IN DATABASE platform SET search_path = engine",
    "ALTER ROLE engine_rw IN DATABASE project_00000000000040008000000000000000 SET search_path = engine",
    # anything added to the one statement
    "ALTER ROLE engine_rw IN DATABASE {db} SET search_path = engine, core",
    "ALTER ROLE engine_rw IN DATABASE {db} SET search_path = engine; ALTER ROLE engine_rw SUPERUSER",
    "ALTER ROLE engine_rw IN DATABASE {db} SET search_path = engine\n",
    "ALTER ROLE engine_rw SUPERUSER",
])
def test_the_function_refuses_anything_but_its_one_statement(project, dsn, statement):
    db = projectdb.database_name(project["pid"])
    with _connect(dsn, db) as conn, pytest.raises(psycopg.errors.RaiseException, match="refused"):
        conn.execute("select aisc_setup.apply_role_setting(%s)", (statement.format(db=db),))


@needs_database
@pytest.mark.parametrize("role", list(PAIRS))
def test_the_function_sets_a_module_roles_own_search_path_in_this_database(project, dsn, role):
    db = projectdb.database_name(project["pid"])
    with _connect(dsn, db) as conn:
        conn.execute("select aisc_setup.apply_role_setting(%s)",
                     (f"ALTER ROLE {role} IN DATABASE {db} SET search_path = {PAIRS[role]}",))
        got = conn.execute(
            "select array_to_string(s.setconfig, ',') from pg_db_role_setting s"
            " join pg_database d on d.oid = s.setdatabase join pg_roles r on r.oid = s.setrole"
            " where d.datname = current_database() and r.rolname = %s", (role,)).fetchone()[0]
    assert got == f"search_path={PAIRS[role]}"


@needs_database
@pytest.mark.parametrize("role", ["qualification_rw", "engine_rw", "controls_rw", "dashboard_ro"])
def test_only_platform_rw_may_call_it(project, dsn, role):
    db = projectdb.database_name(project["pid"])
    try:
        conn = _connect(dsn, db, role=role)
    except psycopg.OperationalError:
        pytest.skip(f"{role} cannot connect to a project database here")
    with conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("select aisc_setup.apply_role_setting(%s)",
                     (f"ALTER ROLE engine_rw IN DATABASE {db} SET search_path = engine",))
    _wait_until_closed(dsn, db, role)


@needs_database
@needs_superuser
def test_the_function_is_owned_by_the_superuser_and_runs_as_its_owner(project, dsn):
    db = projectdb.database_name(project["pid"])
    with _connect(_su(), db) as conn:
        owner_is_super, definer, config, public = conn.execute(
            "select r.rolsuper, p.prosecdef, array_to_string(p.proconfig, ','),"
            " has_function_privilege('public', p.oid, 'EXECUTE')"
            " from pg_proc p join pg_roles r on r.oid = p.proowner"
            " where p.oid = to_regprocedure('aisc_setup.apply_role_setting(text)')").fetchone()
    assert owner_is_super and definer, "P1-D1: SECURITY DEFINER, owned by the superuser"
    assert config == "search_path=pg_catalog"
    assert public is False, "P1-D1: EXECUTE is revoked from PUBLIC"


@needs_superuser
def test_install_setup_function_puts_it_into_a_database_made_without_it():
    name = f"pytest_setting_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(_su(), autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {} TEMPLATE template0").format(sql.Identifier(name)))
    try:
        with _connect(_su(), name) as conn:
            assert conn.execute("select to_regprocedure('aisc_setup.apply_role_setting(text)')").fetchone()[0] is None
            assert projectdb.install_setup_function(conn, _su()) is True
            assert projectdb.install_setup_function(conn, _su()) is False, "a second call changes nothing"
            definer, platform_may, public_may = conn.execute(
                "select p.prosecdef, has_function_privilege('platform_rw', p.oid, 'EXECUTE'),"
                " has_function_privilege('public', p.oid, 'EXECUTE')"
                " from pg_proc p where p.oid = to_regprocedure('aisc_setup.apply_role_setting(text)')").fetchone()
            schema_public = conn.execute("select has_schema_privilege('public', 'aisc_setup', 'USAGE')").fetchone()[0]
        assert definer and platform_may and not public_may and not schema_public
    finally:
        with psycopg.connect(_su(), autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@needs_superuser
def test_provision_as_the_superuser_makes_what_the_platform_would():
    """A database the isolate tool provisions is owned by platform_rw, and so is every schema
    the template makes in it."""
    pid = str(uuid.uuid4())
    name = projectdb.database_name(pid)
    try:
        assert projectdb.provision_as(_su(), pid, set_role="platform_rw", owner="platform_rw") == name
        with _connect(_su(), name) as conn:
            owner = conn.execute("select pg_get_userbyid(datdba) from pg_database where datname = %s",
                                 (name,)).fetchone()[0]
            schemas = dict(conn.execute(
                "select nspname, pg_get_userbyid(nspowner) from pg_namespace where nspname = any(%s)",
                (["provision", "controls", "llm", "project", *PAIRS.values()],)).fetchall())
            applied = [r[0] for r in conn.execute("select name from provision.template_migration order by 1")]
        assert owner == "platform_rw"
        assert set(schemas.values()) == {"platform_rw"} and len(schemas) == 8, schemas
        assert applied == sorted(p.name for p in projectdb.TEMPLATE.glob("*.sql"))
    finally:
        projectdb.drop(_su(), pid)
