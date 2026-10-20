"""The one door through which the template sets a module role's search_path.

platform_rw applies the template but cannot run
`ALTER ROLE <another role> IN DATABASE ... SET` on PG14, so templates 0007..0010 call
aisc_setup.apply_role_setting, a SECURITY DEFINER function owned by the superuser that
init/project-databases.sql puts into template1. It must run that one statement for the four
module roles, each with its own schema, in the database it is called in, and refuse anything
else; only platform_rw may call it.

Needs PLATFORM_TEST_DATABASE_URL (platform_rw) and PLATFORM_TEST_SUPERUSER_URL on a throwaway.
"""
from __future__ import annotations

import os
import time

import psycopg
import pytest
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
    assert owner_is_super and definer, "SECURITY DEFINER, owned by the superuser"
    assert config == "search_path=pg_catalog"
    assert public is False, "EXECUTE is revoked from PUBLIC"
