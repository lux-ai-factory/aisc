"""The relay's connection to a project's database: only a database that is gone (or closed to the platform)
lets the relay go on without that database's outbox. Any other failure, such as too many connections,
leaves the whole log for the next pass, so the platform's events of that project are never relayed ahead of
the project's own."""
from __future__ import annotations

import uuid
from contextlib import contextmanager

import psycopg
import pytest
from psycopg import errors

from platform_service.ledger import relay
from tests.conftest import needs_database


def _refusing(exc):
    def connect(*args, **kwargs):
        raise exc
    return connect


@needs_database
def test_a_database_that_does_not_exist_is_none():
    assert relay._project_conn(str(uuid.uuid4())) is None


@pytest.mark.parametrize("exc", [
    # a failed connect has no result, so psycopg carries the server's message, not its SQLSTATE
    psycopg.OperationalError('connection failed: FATAL:  database "project_x" does not exist'),
    psycopg.OperationalError('connection failed: FATAL:  permission denied for database "project_x"\n'
                             'DETAIL:  User does not have CONNECT privilege.'),
])
def test_gone_or_closed_is_none(monkeypatch, exc):
    monkeypatch.setattr(relay.psycopg, "connect", _refusing(exc))
    assert relay._project_conn(str(uuid.uuid4())) is None


@pytest.mark.parametrize("exc", [
    errors.TooManyConnections("sorry, too many clients already"),
    psycopg.OperationalError("connection failed: FATAL:  sorry, too many clients already"),
    psycopg.OperationalError("connection failed: Connection refused"),
])
def test_any_other_failure_is_unreachable(monkeypatch, exc):
    monkeypatch.setattr(relay.psycopg, "connect", _refusing(exc))
    with pytest.raises(relay.ProjectUnreachable):
        relay._project_conn(str(uuid.uuid4()))


def test_an_unreachable_project_leaves_its_whole_log_for_the_next_pass(monkeypatch):
    from platform_service.ledger import provision

    read = []

    @contextmanager
    def held(log, wait=False):
        yield True

    monkeypatch.setattr(provision, "database_for", lambda pid: "project_log")
    monkeypatch.setattr(relay, "_log_lock", held)
    monkeypatch.setattr(relay.psycopg, "connect", _refusing(errors.TooManyConnections("too many clients")))
    monkeypatch.setattr(relay, "_pending", lambda pid, project: read.append(pid) or [])
    stats = relay.RelayStats()
    relay._relay_log(str(uuid.uuid4()), stats)
    assert read == [], "the platform's events were read without the project's"
    assert stats.pending == 1
