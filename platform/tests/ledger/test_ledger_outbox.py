"""O1-O3: the outbox of a project database (T7, I3). Apps hold no right on the outbox table; they call
`ledger.emit(event jsonb)`, which stamps the role that called it and the database's own time, so an app
can't pass itself off as another or back-date an event (R2.1). The call returns nothing, so no ORM
RETURNING is involved (R3.3). Only the platform reads, marks and keeps delivery state."""
from __future__ import annotations

import json
import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import projectdb

from tests.ledger.conftest import needs_db, SUPERUSER_DSN, need

pytestmark = needs_db

EMITTERS = ["qualification_rw", "controls_rw", "control_objectives_rw", "report_composer_rw", "platform_rw"]
APPS = ["qualification_rw", "controls_rw", "control_objectives_rw", "report_composer_rw"]
OTHERS = ["engine_rw", "report_ro", "inspector_ro"]


@pytest.fixture(autouse=True)
def _superuser():
    need(SUPERUSER_DSN, "PLATFORM_TEST_SUPERUSER_URL is not set")


def connect(pid):
    return psycopg.connect(make_conninfo(SUPERUSER_DSN, dbname=projectdb.database_name(pid)))


def as_role(pid, role, statement, params=()):
    """Run as a module role. The emitter reads session_user, so the role logs in as itself."""
    with connect(pid) as conn:
        conn.execute(f'SET SESSION AUTHORIZATION "{role}"')
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else None


def as_superuser(pid, statement, params=()):
    with connect(pid) as conn:
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else None


def event(**over):
    e = {"event_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4()), "action": "controls.submission.closed",
         "item_type": "submission", "item_id": "s1", "details": {}}
    e.update(over)
    return e


EMIT = "SELECT ledger.emit(%s::jsonb)"


def emit(pid, role, e):
    as_role(pid, role, EMIT, (json.dumps(e),))
    return e["event_id"]


def row(pid, event_id, columns="db_role, occurred_at"):
    return as_superuser(pid, f"SELECT {columns} FROM ledger.outbox WHERE event_id = %s", (event_id,))


@pytest.mark.parametrize("role", EMITTERS)
def test_every_emitting_role_can_emit(project, role):
    assert row(project["pid"], emit(project["pid"], role, event()))


def test_the_row_names_the_role_that_emitted_it_whatever_was_sent(project):
    event_id = emit(project["pid"], "controls_rw", event(db_role="platform_rw"))
    assert row(project["pid"], event_id, "db_role") == [("controls_rw",)]


def test_the_time_is_the_databases_whatever_was_sent(project):
    before = as_superuser(project["pid"], "SELECT clock_timestamp()")[0][0]
    event_id = emit(project["pid"], "controls_rw", event(occurred_at="2001-01-01T00:00:00Z"))
    [(occurred_at,)] = row(project["pid"], event_id, "occurred_at")
    assert occurred_at >= before


def test_emit_returns_nothing(project):
    """A plain SELECT of a void function: Prisma $executeRaw and SQLAlchemy text() can run it."""
    assert as_role(project["pid"], "controls_rw", EMIT, (json.dumps(event()),)) in ([("",)], [(None,)])


def test_a_rolled_back_transaction_leaves_no_event(project):
    e = event()
    with connect(project["pid"]) as conn:
        conn.execute('SET SESSION AUTHORIZATION "controls_rw"')
        conn.execute(EMIT, (json.dumps(e),))
        conn.rollback()
    assert row(project["pid"], e["event_id"]) == []


@pytest.mark.parametrize("action", ["request.witnessed", "request.unverified", "flower.request", "pgadmin.request",
                                    "ledger.rejected", "ledger.reanchored", "page.opened"])
def test_an_app_cannot_emit_the_platforms_own_actions(project, action):
    with pytest.raises(psycopg.errors.RaiseException):
        emit(project["pid"], "controls_rw", event(action=action))


@pytest.mark.parametrize("statement", [
    "SELECT * FROM ledger.outbox",
    "INSERT INTO ledger.outbox (event_id, action) VALUES (gen_random_uuid(), 'x')",
    "UPDATE ledger.outbox SET item_id = 'x'",
    "DELETE FROM ledger.outbox",
    "TRUNCATE ledger.outbox",
])
@pytest.mark.parametrize("role", APPS)
def test_an_app_has_no_right_on_the_table_itself(project, role, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_role(project["pid"], role, statement)


@pytest.mark.parametrize("role", OTHERS)
def test_roles_that_are_not_emitters_cannot_emit(project, role):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        emit(project["pid"], role, event())


@pytest.mark.parametrize("table", ["ledger.delivered", "ledger.action_binding"])
@pytest.mark.parametrize("role", APPS + OTHERS)
def test_delivery_state_is_the_platforms_alone(project, role, table):
    """No app reads or writes the relay's state. pgAdmin's inspector_ro reads every table of a project
    database by design (pg_read_all_data, S8: only the names behind references are kept from it), so for
    it only the write is refused."""
    statements = [f"INSERT INTO {table} DEFAULT VALUES"] + ([] if role == "inspector_ro" else [f"SELECT * FROM {table}"])
    for statement in statements:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            as_role(project["pid"], role, statement)


def test_a_malformed_event_is_refused_in_the_apps_transaction(project):
    with pytest.raises(psycopg.errors.RaiseException):
        emit(project["pid"], "controls_rw", {"action": "controls.submission.closed"})   # no event_id


def test_emit_refuses_every_action_whose_origin_is_not_an_app(project):
    """The SQL list is generated from the registry (origin platform or browser), so they can't drift
    (third review n11, fourth review 2)."""
    from platform_service.ledger.registry import REGISTRY

    platform_only = sorted(name for name, action in REGISTRY.items() if action.origin != "app")
    assert platform_only
    for action in platform_only:
        with pytest.raises(psycopg.errors.RaiseException):
            emit(project["pid"], "controls_rw", event(action=action))


def test_emit_keeps_fields_only_the_platform_may_set_for_the_relay_to_reject(project):
    """Refusing them in emit would roll back the business write; the relay rejects them instead (n-b)."""
    event_id = emit(project["pid"], "controls_rw", event(content_sha256="0" * 64, recorded_at="2001-01-01"))
    [(extra,)] = row(project["pid"], event_id, "extra")
    assert extra == {"content_sha256": "0" * 64, "recorded_at": "2001-01-01"}
