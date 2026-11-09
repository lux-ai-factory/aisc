"""The projects' mock databases, against a stand-in server: no database is touched."""
import re

import psycopg
import pytest

from chart_assistant import mock_store
from chart_assistant.mock_store import MockStore

PID = "0b5446b0-3bcf-4747-9a47-996747111b86"
DESCRIPTION = {"targets": ["T"], "metrics": [{"name": "M", "dimensions": {"category": {"type": "text", "values": ["a"]}}}]}


class Server:
    """Databases by name; what was run where. fill_fails: filling a database raises, as a broken load would."""

    def __init__(self):
        self.databases, self.log, self.fill_fails = set(), [], False

    def connect(self, url, autocommit=False):
        return Connection(self, url.rsplit("/", 1)[1])


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class Connection:
    def __init__(self, server, database):
        self.server, self.database = server, database

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        s = self.server
        s.log.append((self.database, sql))
        if sql.startswith("SELECT 1 FROM pg_database"):
            return Result([(1,)] if params[0] in s.databases else [])
        if sql.startswith("SELECT datname FROM pg_database"):
            return Result([(d,) for d in sorted(s.databases)])
        if m := re.fullmatch(r'CREATE DATABASE "(\w+)"', sql):
            s.databases.add(m[1])
        elif m := re.fullmatch(r'DROP DATABASE IF EXISTS "(\w+)"', sql):
            s.databases.discard(m[1])
        elif m := re.fullmatch(r'ALTER DATABASE "(\w+)" RENAME TO "(\w+)"', sql):
            s.databases.remove(m[1])
            s.databases.add(m[2])
        elif "CREATE TABLE" in sql:
            assert self.database in s.databases
            if s.fill_fails:
                raise psycopg.OperationalError("the fill failed")
        return Result([])


@pytest.fixture
def server(monkeypatch):
    s = Server()
    monkeypatch.setattr(mock_store.psycopg, "connect", s.connect)
    return s


def store():
    return MockStore("postgresql://assistant_mock@postgres/postgres")


def fills(server):
    return [db for db, sql in server.log if "CREATE TABLE" in sql]


def test_a_mock_database_whose_fill_fails_is_not_left_behind_to_be_taken_as_made(server):
    server.fill_fails = True
    with pytest.raises(psycopg.OperationalError):
        store().runner(PID, DESCRIPTION)
    assert not {d for d in server.databases if d.startswith("assistant_mock_")}
    server.fill_fails = False
    store().runner(PID, DESCRIPTION)
    assert len(fills(server)) == 2
    assert len(server.databases) == 1


def test_a_made_mock_database_is_filled_once(server):
    store().runner(PID, DESCRIPTION)
    store().runner(PID, DESCRIPTION)
    assert len(fills(server)) == 1
    (name,) = server.databases
    assert re.fullmatch(r"assistant_mock_[0-9a-f]{32}_[0-9a-f]{12}", name)


def test_a_new_description_drops_the_projects_older_mock_databases_and_no_other_projects(server):
    other = "a796ca53-f5d5-4eb8-9f58-83db0f095577"
    store().runner(other, DESCRIPTION)
    store().runner(PID, DESCRIPTION)
    store().runner(PID, {**DESCRIPTION, "targets": ["T", "U"]})
    server.databases.add("postgres")
    assert len(server.databases) == 3
    store().runner(PID, {**DESCRIPTION, "targets": ["U"]})
    mine = {d for d in server.databases if d.startswith("assistant_mock_" + PID.replace("-", ""))}
    theirs = {d for d in server.databases if d.startswith("assistant_mock_" + other.replace("-", ""))}
    assert len(mine) == 1 and len(theirs) == 1 and "postgres" in server.databases
