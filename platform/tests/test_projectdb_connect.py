"""One way to open a project's database (projectdb.connect): every caller learns the same way that the
database is gone, whether it was dropped before the call or is simply not there."""
from __future__ import annotations

import uuid

import pytest

from platform_service import catalogue, db, llm_store, projectdb
from platform_service.routes import projects as project_routes
from tests.conftest import DSN, needs_database

pytestmark = needs_database

OPENERS = {
    "projectdb.connect": projectdb.connect,
    "db.project_connection": db.project_connection,
    "catalogue._connect": catalogue._connect,
    "llm_store.connect": llm_store.connect,
    "routes.projects.projectdb_connection": project_routes.projectdb_connection,
}


@pytest.mark.parametrize("opener", sorted(OPENERS))
def test_a_project_without_a_database_is_gone_for_every_caller(opener):
    with pytest.raises(db.ProjectDatabaseGone):
        OPENERS[opener](str(uuid.uuid4()))


@pytest.mark.parametrize("opener", sorted(OPENERS))
def test_a_dropped_project_database_is_gone_for_every_caller(opener):
    pid = str(uuid.uuid4())
    projectdb.provision(DSN, pid)
    with OPENERS[opener](pid) as conn:
        assert conn.execute("SELECT current_database() AS d").fetchone()["d"] == projectdb.database_name(pid)
    projectdb.drop(DSN, pid)
    with pytest.raises(db.ProjectDatabaseGone):
        OPENERS[opener](pid)


def test_connect_takes_the_connection_options():
    pid = str(uuid.uuid4())
    projectdb.provision(DSN, pid)
    try:
        with projectdb.connect(pid, autocommit=True, row_factory=None) as conn:
            assert conn.autocommit
            assert conn.execute("SELECT 1").fetchone() == (1,)
    finally:
        projectdb.drop(DSN, pid)
