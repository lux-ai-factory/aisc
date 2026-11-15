"""Running the migration that closes what deleted projects left a second time changes nothing: the rows it
closed keep the time and reason of the first run, and a live project's rows stay open."""
from __future__ import annotations

import uuid
from pathlib import Path

import psycopg

from tests.conftest import DSN, MIGRATE_DSN
from tests.ledger.conftest import needs_db

pytestmark = needs_db
MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "0011_close_what_deleted_projects_left_without_a_log.sql"


def _leftovers(conn, pid: str) -> tuple[str, str]:
    request = str(uuid.uuid4())
    conn.execute("INSERT INTO ledger.witness (request_id, mode, app, method, route_path, project_pid, verified)"
                 " VALUES (%s, 'record', 'platform', 'DELETE', '/api/projects/x', %s, true)", (request, pid))
    event = str(uuid.uuid4())
    conn.execute("INSERT INTO core.outbox (event_id, emitter, project_pid, action) VALUES (%s, 'platform', %s,"
                 " 'project.deleted')", (event, pid))
    return request, event


def _closing_state(conn, request, event, kept_request) -> tuple:
    closed = conn.execute("SELECT closed_at, closed_reason FROM ledger.witness WHERE request_id = %s",
                          (request,)).fetchone()
    sent = conn.execute("SELECT delivered_at, delivered_reason FROM core.outbox WHERE event_id = %s",
                        (event,)).fetchone()
    kept_open = conn.execute("SELECT closed_at IS NULL FROM ledger.witness WHERE request_id = %s",
                             (kept_request,)).fetchone()[0]
    return (*closed, *sent, kept_open)


def _migrate() -> None:
    """The migration again, as the platform runs its migrations: platform_migrator."""
    with psycopg.connect(MIGRATE_DSN, autocommit=True) as conn:
        conn.execute(MIGRATION.read_text())


def test_the_migration_runs_again_without_changing_what_it_closed(project):
    gone = str(uuid.uuid4())
    with psycopg.connect(DSN, autocommit=True) as conn:
        request, event = _leftovers(conn, gone)
        kept_request, _ = _leftovers(conn, project["pid"])
        _migrate()
        first = _closing_state(conn, request, event, kept_request)
        _migrate()
        again = _closing_state(conn, request, event, kept_request)
    assert first[0] is not None and first[-1] is True, "the first run did not close the leftovers only"
    assert again == first
