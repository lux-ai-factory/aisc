"""O1: the outbox of a project database (T7). Apps may only add rows; the row says which app added it
whatever the app sends; only the platform reads, marks and keeps delivery state."""
from __future__ import annotations

import uuid

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import needs_database
from tests.ledger.conftest import SUPERUSER_DSN

pytestmark = [needs_database, pytest.mark.skipif(not SUPERUSER_DSN, reason="PLATFORM_TEST_SUPERUSER_URL is not set")]

MODULE_ROLES = ["qualification_rw", "controls_rw", "control_objectives_rw", "report_composer_rw", "platform_rw"]


def as_role(pid, role, statement, params=()):
    with psycopg.connect(make_conninfo(SUPERUSER_DSN, dbname=projectdb.database_name(pid))) as conn:
        conn.execute(f'SET ROLE "{role}"')
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else None


def as_superuser(pid, statement, params=()):
    with psycopg.connect(make_conninfo(SUPERUSER_DSN, dbname=projectdb.database_name(pid))) as conn:
        cur = conn.execute(statement, params)
        return cur.fetchall() if cur.description else None


INSERT = ("INSERT INTO ledger.outbox (event_id, db_role, request_id, action, item_type, item_id)"
          " VALUES (%s, %s, %s, 'controls.submission.closed', 'submission', 's1')")


@pytest.mark.parametrize("role", MODULE_ROLES)
def test_every_module_role_can_add_a_row(project, role):
    as_role(project["pid"], role, INSERT, (str(uuid.uuid4()), role, str(uuid.uuid4())))


def test_the_row_names_the_role_that_added_it_whatever_was_sent(project):
    event_id = str(uuid.uuid4())
    as_role(project["pid"], "controls_rw", INSERT, (event_id, "platform_rw", str(uuid.uuid4())))
    assert as_superuser(project["pid"], "SELECT db_role FROM ledger.outbox WHERE event_id = %s",
                        (event_id,)) == [("controls_rw",)]


@pytest.mark.parametrize("statement", ["SELECT * FROM ledger.outbox",
                                       "UPDATE ledger.outbox SET item_id = 'x'",
                                       "DELETE FROM ledger.outbox"])
@pytest.mark.parametrize("role", ["qualification_rw", "controls_rw", "control_objectives_rw", "report_composer_rw"])
def test_an_app_cannot_read_change_or_remove_rows(project, role, statement):
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        as_role(project["pid"], role, statement)


def test_delivery_state_is_the_platforms_alone(project):
    for role in ("controls_rw", "qualification_rw"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            as_role(project["pid"], role, "SELECT * FROM ledger.delivered")
