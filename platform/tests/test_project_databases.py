"""One database per project, made by the platform when the project is made.

The name rule is tested without a database. The rest runs against the real
Postgres, like the membership tests, and skips when there is none.
"""
import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import db, projectdb
from tests.conftest import needs_database

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"


def test_the_database_is_named_after_the_pid():
    # The same example is asserted in apps/controls/test/unit/projectDb.test.ts:
    # two languages, one rule.
    assert projectdb.database_name(PID) == "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"
    assert projectdb.database_name(PID.upper()) == "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"


@pytest.mark.parametrize("bad", ["", "abc", "../platform", PID + "x", PID + "\n", "project_x; drop database platform"])
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
    # Isolation 2026-09-25 (01-specs.md I2.1): the template now lists every module role
    # (0007..0010 let qualification_rw, control_objectives_rw, engine_rw and
    # report_composer_rw connect), so the role that must be refused is one it never
    # lists: the catalogue's, which holds no project's data.
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        _as(dsn, "catalogue_rw", projectdb.database_name(created["pid"]))


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


@needs_database
def test_a_database_made_before_its_template_fails_is_not_left_orphaned(
    client, as_user, unique, monkeypatch, dsn
):
    """CREATE DATABASE can succeed and the template step can still fail (a bad
    template file, a lock, a dropped connection). Either way this is "made, or
    not at all": no core.project row and no project_<hex> database."""
    captured = {}
    original_create_project = db.create_project

    def capture(*args, **kwargs):
        created = original_create_project(*args, **kwargs)
        captured["pid"] = created["pid"]
        return created

    monkeypatch.setattr(db, "create_project", capture)

    def refuse(*_args, **_kwargs):
        raise psycopg.OperationalError("simulated: the template step fails")

    # The name `migrate` bound inside projectdb, called after CREATE DATABASE
    # has already run: this is the exact "database exists, template failed"
    # ordering the fix is for.
    monkeypatch.setattr(projectdb, "migrate", refuse)

    slug = unique()
    response = client.post("/projects", json={"name": slug}, headers=as_user("alice"))
    assert response.status_code == 503
    assert client.get(f"/projects/{slug}", headers=as_user("alice")).status_code == 404

    assert "pid" in captured, "db.create_project was never reached"
    name = projectdb.database_name(captured["pid"])
    with psycopg.connect(dsn) as conn:
        left_behind = conn.execute(
            "select 1 from pg_database where datname = %s", (name,)
        ).fetchone()
    assert left_behind is None


@needs_database
def test_one_project_that_cannot_be_provisioned_does_not_stop_the_others(
    client, as_user, unique, monkeypatch
):
    a = client.post("/projects", json={"name": unique("a")}, headers=as_user("alice")).json()["pid"]
    b = client.post("/projects", json={"name": unique("b")}, headers=as_user("alice")).json()["pid"]
    a, b = str(a), str(b)

    tried = []

    def provision(_dsn, pid):
        tried.append(str(pid))
        if str(pid) == a:
            raise psycopg.OperationalError("simulated: this one cannot be made")
        return projectdb.database_name(pid)

    monkeypatch.setattr(projectdb, "provision", provision)
    # As at start: the projects are not yet listed. monkeypatch puts the real
    # state back afterwards, so nothing else is provisioned by this test.
    monkeypatch.setattr(db, "_unprovisioned", None)

    db.pool()
    assert a in tried and b in tried, "the failure stopped the sweep"
    assert db._unprovisioned is not None and a in db._unprovisioned and b not in db._unprovisioned

    # The next call tries the failed one again, and only it.
    monkeypatch.setattr(db, "RETRY_SECONDS", 0.0)
    tried.clear()
    monkeypatch.setattr(projectdb, "provision", lambda _dsn, pid: tried.append(str(pid)))
    db.pool()
    assert tried == [a]
    assert db._unprovisioned == set()


@needs_database
def test_a_failed_setup_is_done_again_at_the_next_call(monkeypatch):
    from platform_service import db as dbmod

    real_migrate = dbmod.migrate
    calls = []

    def migrate_once_failing(conn, *args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise psycopg.OperationalError("simulated: the database is still starting")
        return real_migrate(conn, *args, **kwargs)

    monkeypatch.setattr(dbmod, "migrate", migrate_once_failing)
    monkeypatch.setattr(dbmod, "_migrated", False)
    with pytest.raises(psycopg.OperationalError):
        dbmod.pool()
    assert dbmod._migrated is False
    dbmod.pool()
    assert dbmod._migrated is True
    assert len(calls) == 2


@needs_database
def test_a_drop_that_fails_after_a_failed_provision_is_logged(client, as_user, unique, monkeypatch, caplog):
    def refuse(*_args, **_kwargs):
        raise psycopg.OperationalError("simulated: no database for you")

    def drop_fails(*_args, **_kwargs):
        raise psycopg.OperationalError("simulated: cannot drop either")

    monkeypatch.setattr(projectdb, "provision", refuse)
    monkeypatch.setattr(projectdb, "drop", drop_fails)
    with caplog.at_level("ERROR", logger="platform_service.app"):
        response = client.post("/projects", json={"name": unique()}, headers=as_user("alice"))
    assert response.status_code == 503
    assert any("could not drop the half-made database" in r.getMessage() for r in caplog.records)
