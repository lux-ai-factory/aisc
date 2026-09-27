import uuid

import psycopg
import pytest


def test_migrations_create_the_tables(db):
    with db.connection() as conn:
        names = {r["table_name"] for r in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'connector'"
        )}
    assert {"connector", "secret", "operation_policy", "access_token", "publication",
            "call_log", "schema_migration"} <= names


def test_migrate_is_idempotent(database_url, db):
    from aisc_connectors import db as dbm

    assert dbm.migrate(database_url) == []


def test_one_target_access_connector_per_project(db):
    project = uuid.uuid4()
    insert = ("INSERT INTO connector.connector (pid, project_pid, ai_system_pid, name, slug, kind,"
              " environment, is_target_access, created_by) VALUES (%s, %s, %s, %s, %s, 'manual',"
              " 'sandbox', true, 'test')")
    with db.connection() as conn:
        conn.execute(insert, (uuid.uuid4(), project, uuid.uuid4(), "A", "a"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.connection() as conn:
            conn.execute(insert, (uuid.uuid4(), project, uuid.uuid4(), "B", "b"))
