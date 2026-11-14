"""The platform's objects belong to platform_owner; platform_rw keeps DML only.

platform_rw is the role the platform service's requests run as. It may read and write rows, but it owns
no database, schema or table, so it can neither lift a guard trigger nor truncate or drop what the
guards protect. Provisioning and deletion go through the platform_migrator login (PLATFORM_MIGRATE_DATABASE_URL).
"""
from __future__ import annotations

import os
import uuid

import psycopg
import pytest

from platform_service import projectdb
from tests.conftest import needs_database, one, project_db

PLATFORM_SCHEMAS = ("project", "evidence", "trace", "ledger", "provision", "connection", "helper", "llm", "target")
MODULE_SCHEMAS = ("qualification", "controls", "control_objectives", "report_composer", "engine")


def _db_exists(dsn, pid):
    with psycopg.connect(dsn) as conn:
        return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                            (projectdb.database_name(pid),)).fetchone() is not None


@needs_database
def test_a_project_database_belongs_to_platform_owner(project, dsn):
    owner = one(dsn, project, "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()")
    assert owner[0] == "platform_owner"


@needs_database
def test_the_platform_schemas_and_their_tables_belong_to_platform_owner(project, dsn):
    with project_db(dsn, project) as conn:
        schemas = {r[0] for r in conn.execute(
            "SELECT DISTINCT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = ANY(%s)",
            (list(PLATFORM_SCHEMAS),))}
        tables = {r[0] for r in conn.execute(
            "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = ANY(%s)", (list(PLATFORM_SCHEMAS),))}
    assert schemas == {"platform_owner"}
    assert tables == {"platform_owner"}


@needs_database
@pytest.mark.parametrize("schema", MODULE_SCHEMAS)
def test_each_module_schema_is_handed_to_its_owner(project, dsn, schema):
    owner = one(dsn, project, "SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = %s", (schema,))
    assert owner[0] == f"{schema}_owner"


@needs_database
def test_platform_rw_cannot_disable_the_trace_guard(project, dsn):
    with project_db(dsn, project, role="platform_rw") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("ALTER TABLE trace.call DISABLE TRIGGER call_append_only")


@needs_database
def test_platform_rw_cannot_truncate_card_versions(project, dsn):
    with project_db(dsn, project, role="platform_rw") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("TRUNCATE project.system CASCADE")


@needs_database
def test_platform_rw_cannot_drop_a_module_schema(project, dsn):
    with project_db(dsn, project, role="platform_rw") as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DROP SCHEMA qualification CASCADE")


@needs_database
def test_platform_rw_may_not_delete_card_versions_nor_hold_trigger_or_truncate(project, dsn):
    with project_db(dsn, project) as conn:
        assert conn.execute("SELECT has_table_privilege('platform_rw', 'project.system', 'DELETE')").fetchone()[0] is False
        held = conn.execute("""
            SELECT c.oid::regclass::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = ANY(%s) AND c.relkind IN ('r', 'p')
               AND (has_table_privilege('platform_rw', c.oid, 'TRIGGER')
                    OR has_table_privilege('platform_rw', c.oid, 'TRUNCATE'))
             ORDER BY 1""", (list(PLATFORM_SCHEMAS),)).fetchall()
    assert held == [], f"platform_rw holds TRIGGER or TRUNCATE on {[r[0] for r in held]}"


@needs_database
def test_platform_rw_only_appends_to_the_run_trace(project, dsn):
    with project_db(dsn, project) as conn:
        for priv, expected in (("INSERT", True), ("SELECT", True), ("UPDATE", False), ("DELETE", False)):
            got = conn.execute("SELECT has_table_privilege('platform_rw', 'trace.call', %s)", (priv,)).fetchone()[0]
            assert got is expected, f"{priv} on trace.call: {got}"


@needs_database
def test_the_platform_database_tables_belong_to_platform_owner(dsn):
    with psycopg.connect(dsn) as conn:
        owners = {r[0] for r in conn.execute(
            "SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = 'ledger'"
            " OR (schemaname = 'core' AND tablename NOT IN ('project'))")}
    assert owners == {"platform_owner"}


def test_the_service_needs_a_migrator_address(monkeypatch):
    from platform_service import db

    assert callable(getattr(db, "migrate_dsn", None)), "platform_service.db has no migrate_dsn()"
    monkeypatch.delenv("PLATFORM_MIGRATE_DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError):
        db.migrate_dsn()


@needs_database
def test_platform_rw_cannot_create_a_project_database(dsn):
    pid = str(uuid.uuid4())
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            projectdb.provision(dsn, pid)
    finally:
        if _db_exists(dsn, pid):
            projectdb.drop(dsn, pid)


@needs_database
def test_deleting_a_project_ends_other_roles_sessions_and_drops_it(client, admin, project, dsn):
    held = project_db(dsn, project, role="qualification_rw")          # an app's open session
    try:
        gone = client.request("DELETE", f"/projects/{project['slug']}", json={"confirm_name": project["name"]},
                              headers=admin)
        assert gone.status_code == 204, gone.text
        assert not _db_exists(dsn, project["pid"])
        assert held.closed or held.broken or _session_was_ended(held)
    finally:
        held.close()


def _session_was_ended(conn) -> bool:
    try:
        conn.execute("SELECT 1")
    except psycopg.OperationalError:
        return True
    return False


@needs_database
def test_the_migrator_address_is_given_to_the_tests():
    """The suite reaches platform_migrator as the service does, so provisioning and deletion are tested as they run."""
    assert os.environ.get("PLATFORM_TEST_MIGRATE_DATABASE_URL"), "PLATFORM_TEST_MIGRATE_DATABASE_URL is not set"
