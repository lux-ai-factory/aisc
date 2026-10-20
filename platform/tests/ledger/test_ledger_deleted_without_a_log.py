"""Projects deleted while the ledger pool was empty never had a log: what they left (witness records of
their requests, platform events such as their own deletion) had nowhere to go, and the relay counted it as
pending on every pass, for ever. Migration 0011 closes those rows, saying why; a project that still exists,
or has a log, keeps its rows as they are. A project can no longer be deleted before it has a log
(test_ledger_platform_events.py), so none are made any more."""
from __future__ import annotations

import uuid
from pathlib import Path

import psycopg

from tests.conftest import DSN
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


def test_what_a_project_deleted_without_a_log_left_is_closed_and_no_longer_pending(project, memory_ledger):
    from platform_service.ledger import relay

    gone = str(uuid.uuid4())                                       # no project row, no pool database
    with psycopg.connect(DSN, autocommit=True) as conn:
        request, event = _leftovers(conn, gone)
        kept_request, kept_event = _leftovers(conn, project["pid"])
        conn.execute(MIGRATION.read_text())
        closed = conn.execute("SELECT closed_at IS NOT NULL, closed_reason, delivered_seq FROM ledger.witness"
                              " WHERE request_id = %s", (request,)).fetchone()
        sent = conn.execute("SELECT delivered_at IS NOT NULL, delivered_reason, delivered_seq FROM core.outbox"
                            " WHERE event_id = %s", (event,)).fetchone()
        kept = conn.execute("SELECT closed_at IS NULL FROM ledger.witness WHERE request_id = %s",
                            (kept_request,)).fetchone()[0], conn.execute(
            "SELECT delivered_at IS NULL FROM core.outbox WHERE event_id = %s", (kept_event,)).fetchone()[0]
    assert closed[0] and "deleted before it had one" in closed[1] and closed[2] is None
    assert sent[0] and "deleted before it had one" in sent[1] and sent[2] is None
    assert kept == (True, True)
    assert gone not in relay._projects_with_work()


def test_the_migration_runs_again_without_harm():
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(MIGRATION.read_text())
        conn.execute(MIGRATION.read_text())
