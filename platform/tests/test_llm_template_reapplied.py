"""Applying the project database's LLM template a second time leaves the schema exactly as the first apply
made it: same tables, columns, constraints, indexes, triggers, policies and grants."""
from __future__ import annotations

from platform_service import projectdb
from tests.conftest import MIGRATE_DSN, needs_database, project_db
from tests.schema_shape import schema_shape

pytestmark = needs_database
TEMPLATE_FILE = projectdb.TEMPLATE / "0005_llm.sql"


def test_applying_the_llm_template_again_changes_nothing(project, dsn):
    with project_db(MIGRATE_DSN, project) as conn:      # as the platform applies its template
        with conn.transaction():
            conn.execute(TEMPLATE_FILE.read_text())
            once = schema_shape(conn, "llm")
            conn.execute(TEMPLATE_FILE.read_text())
            again = schema_shape(conn, "llm")
    assert once["tables"], "the template made no table"
    assert again == once
