"""CL1: the test suite's own cleanup removes exactly what it recorded (fourth review 1). Phase 1 makes
`ledger.pool` and `ledger.state`; the other tables join as their phases build them."""
from __future__ import annotations

import uuid

import psycopg

from tests.conftest import DSN
from tests.ledger.conftest import needs_db, remove_made

pytestmark = needs_db


def test_cleanup_removes_what_was_recorded_and_nothing_else(memory_ledger):
    from platform_service.ledger import naming

    ours, theirs = f"memory:{uuid.uuid4()}", f"memory:{uuid.uuid4()}"
    a, b = naming.pool_name(), naming.pool_name()
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute("INSERT INTO ledger.pool (db, server_id) VALUES (%s, %s), (%s, %s)", (a, ours, b, theirs))
    assert remove_made(DSN, {"pids": set(), "requests": set(), "servers": {ours}, "subs": set()}) == []
    with psycopg.connect(DSN, autocommit=True) as conn:
        left = {r[0] for r in conn.execute("SELECT db FROM ledger.pool WHERE db IN (%s, %s)", (a, b))}
        conn.execute("DELETE FROM ledger.pool WHERE db = %s", (b,))
    assert left == {b}


def test_cleanup_reports_a_failing_statement(memory_ledger, monkeypatch):
    from tests.ledger import conftest

    monkeypatch.setattr(conftest, "CLEANUP", [("ledger.pool", "DELETE FROM ledger.pool WHERE no_such_column = 1")])
    failures = remove_made(DSN, {"pids": set(), "requests": set(), "servers": set(), "subs": set()})
    assert len(failures) == 1 and failures[0].startswith("ledger.pool")
