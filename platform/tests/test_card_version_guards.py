"""A card version is never deleted, and evidence keeps its version.

project.system holds every card version; runs, evidence and reports name one. A version that disappeared
would leave them pointing at nothing, so the table refuses DELETE and TRUNCATE for every role, the
superuser included, and the evidence references restrict instead of cascading. A project is still
removed whole by dropping its database.
"""
from __future__ import annotations

import os

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import db, projectdb
from tests.conftest import ALICE, needs_database, project_db

SUPERUSER = os.environ.get("PLATFORM_TEST_SUPERUSER_URL", "")
needs_superuser = pytest.mark.skipif(not SUPERUSER, reason="no throwaway superuser URL")


def _as_superuser(project):
    return psycopg.connect(make_conninfo(SUPERUSER, dbname=projectdb.database_name(project["pid"])))


def _db_exists(dsn, pid):
    with psycopg.connect(dsn) as conn:
        return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                            (projectdb.database_name(pid),)).fetchone() is not None


@needs_database
@needs_superuser
def test_a_card_version_cannot_be_deleted_even_by_the_superuser(project):
    db.create_version(project["slug"], "MCAS", "v1", None, None, ALICE)
    with _as_superuser(project) as conn, pytest.raises(psycopg.errors.RaiseException, match="is kept"):
        conn.execute("DELETE FROM project.system")


@needs_database
@needs_superuser
def test_card_versions_cannot_be_truncated(project):
    db.create_version(project["slug"], "MCAS", "v1", None, None, ALICE)
    with _as_superuser(project) as conn, pytest.raises(psycopg.errors.RaiseException):
        conn.execute("TRUNCATE project.system CASCADE")


@needs_database
def test_evidence_references_to_a_card_version_restrict(project, dsn):
    with project_db(dsn, project) as conn:
        kinds = {r[0] for r in conn.execute(
            "SELECT confdeltype FROM pg_constraint WHERE confrelid = 'project.system'::regclass"
            " AND conrelid::regclass::text LIKE 'evidence.%'")}
    assert kinds == {"r"}


@needs_database
def test_project_teardown_still_drops_a_database_with_guards(make_project, dsn):
    migrate_dsn = os.environ.get("PLATFORM_TEST_MIGRATE_DATABASE_URL")
    assert migrate_dsn, "PLATFORM_TEST_MIGRATE_DATABASE_URL is not set: teardown must run as platform_migrator"
    p = make_project()
    db.create_version(p["slug"], "MCAS", "v1", None, None, ALICE)
    projectdb.drop(migrate_dsn, p["pid"])
    assert not _db_exists(dsn, p["pid"])
