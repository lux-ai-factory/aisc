"""One database per project, made by the platform when the project is made.

The name rule is tested without a database. The rest runs against the real
Postgres, like the membership tests, and skips when there is none.
"""
import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from tests.conftest import needs_database

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"


def test_the_database_is_named_after_the_pid():
    # The same example is asserted in apps/controls/test/unit/projectDb.test.ts:
    # two languages, one rule.
    assert projectdb.database_name(PID) == "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"
    assert projectdb.database_name(PID.upper()) == "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"


@pytest.mark.parametrize("bad", ["", "abc", "../platform", PID + "x", "project_x; drop database platform"])
def test_anything_but_a_pid_is_refused(bad):
    with pytest.raises(projectdb.NotAPid):
        projectdb.database_name(bad)


def _as(dsn, role, dbname):
    return psycopg.connect(make_conninfo(dsn, user=role, password=role, dbname=dbname), autocommit=True)


@needs_database
def test_making_a_project_makes_its_database(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    name = projectdb.database_name(created["pid"])
    with psycopg.connect(dsn) as conn:
        assert conn.execute("select 1 from pg_database where datname = %s", (name,)).fetchone()
    with _as(dsn, "controls_rw", name) as conn:
        conn.execute("create table controls.probe (x int)")
        conn.execute("drop table controls.probe")


@needs_database
def test_two_projects_share_nothing(client, as_user, unique, dsn):
    a = client.post("/projects", json={"name": unique("a")}, headers=as_user("alice")).json()
    b = client.post("/projects", json={"name": unique("b")}, headers=as_user("alice")).json()
    with _as(dsn, "controls_rw", projectdb.database_name(a["pid"])) as conn:
        conn.execute("create table controls.only_in_a (x int)")
    with _as(dsn, "controls_rw", projectdb.database_name(b["pid"])) as conn:
        found = conn.execute("select to_regclass('controls.only_in_a')").fetchone()[0]
    assert found is None


@needs_database
def test_nobody_but_the_listed_roles_may_connect(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    with pytest.raises(psycopg.OperationalError):
        _as(dsn, "engine_rw", projectdb.database_name(created["pid"]))


@needs_database
def test_provisioning_twice_changes_nothing(client, as_user, unique, dsn):
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    assert projectdb.provision(dsn, created["pid"]) == projectdb.database_name(created["pid"])


@needs_database
def test_a_project_whose_database_cannot_be_made_is_not_made(client, as_user, unique, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise psycopg.OperationalError("simulated: no database for you")

    monkeypatch.setattr(projectdb, "provision", refuse)
    slug = unique()
    response = client.post("/projects", json={"name": slug}, headers=as_user("alice"))
    assert response.status_code == 503
    assert client.get(f"/projects/{slug}", headers=as_user("alice")).status_code == 404
