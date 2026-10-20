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


@pytest.mark.parametrize("given", [PID, PID.upper(), PID.title()])
def test_the_database_is_named_after_the_pid(given):
    # The same example is asserted in apps/controls/test/unit/projectDb.test.ts:
    # two languages, one rule. Any letter case names the same database.
    assert projectdb.database_name(given) == "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"


# Anything that becomes part of a database name must be the hyphenated uuid form.
@pytest.mark.parametrize("bad", ["", "abc", "../platform", PID + "x", PID + "\n", "project_x; drop database platform",
                                 PID.replace("-", ""), "{" + PID + "}", " " + PID, PID[:-1] + "g"])
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
    # The template lists every module role
    # (0007..0010 let qualification_rw, control_objectives_rw, engine_rw and
    # report_composer_rw connect), so the role that must be refused is one it never
    # lists: the catalogue's, which holds no project's data.
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    with pytest.raises(psycopg.OperationalError, match="permission denied"):
        _as(dsn, "catalogue_rw", projectdb.database_name(created["pid"]))


@needs_database
def test_qualification_may_make_temporary_tables_and_no_other_module_may(client, as_user, unique, dsn):
    # qualification's two-level forms migration (20260925150000) keeps its bookkeeping in a
    # temporary table (ON COMMIT DROP). The template revokes every database right from PUBLIC,
    # so template 0011 gives TEMPORARY back to qualification_rw only.
    created = client.post("/projects", json={"name": unique()}, headers=as_user("alice")).json()
    name = projectdb.database_name(created["pid"])
    with _as(dsn, "qualification_rw", name) as conn:
        conn.execute("create temp table t (x int) on commit drop")
    for role in ("controls_rw", "control_objectives_rw", "engine_rw", "report_composer_rw"):
        with _as(dsn, role, name) as conn:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute("create temp table t (x int)")


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
    assert db.wait_for_retry(10)                                      # the retry runs in the background
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


@needs_database
def test_a_slow_dashboard_retry_does_not_hold_up_other_requests(make_project, monkeypatch):
    """The retry of failed dashboard registrations ran inside pool()'s process-wide lock, so every
    request of every project (and Caddy's forward_auth) waited behind a slow or hanging dashboard."""
    import threading
    import time

    from platform_service import dashboard_bridge

    pid = str(make_project()["pid"])
    db.pool()                                                         # the first setup is done
    started = threading.Event()

    def slow_register(*_args, **_kwargs):
        started.set()
        time.sleep(2.0)
        return False

    monkeypatch.setattr(dashboard_bridge, "register", slow_register)
    monkeypatch.setattr(db, "_registered_all", True)
    monkeypatch.setattr(db, "_last_attempt", 0.0)
    db.remember_unregistered(pid)
    retrying = threading.Thread(target=db.pool)
    retrying.start()
    assert started.wait(5), "the retry never ran"
    t0 = time.monotonic()
    db.pool()
    waited = time.monotonic() - t0
    retrying.join(10)
    assert not retrying.is_alive() and db.wait_for_retry(10), "the retry pass never ended"
    assert waited < 0.2, f"pool() waited {waited:.2f}s behind the dashboard retry"
    assert pid in db._unregistered                                    # still failing: kept for the next pass
    db._unregistered.discard(pid)


@needs_database
def test_a_project_that_fails_registration_during_a_retry_stays_waiting(make_project, monkeypatch):
    """The retry runs outside the lock now: a project made (and refused by the dashboard) after the
    retry listed the projects is not in that list, and must not be dropped from the waiting set as if
    it had been deleted."""
    import threading

    from platform_service import dashboard_bridge

    pid = str(make_project()["pid"])
    db.pool()
    newcomer = "0f8fad5b-d9cb-469f-a165-70867728950e"
    real_provision_pending = db._provision_pending

    def provision_while_another_is_made(current):
        maker = threading.Thread(target=db.remember_unregistered, args=(newcomer,))
        maker.start()
        maker.join(5)
        assert not maker.is_alive(), "remember_unregistered waited for a lock the retry holds"
        real_provision_pending(current)

    monkeypatch.setattr(db, "_provision_pending", provision_while_another_is_made)
    monkeypatch.setattr(dashboard_bridge, "register", lambda *_a, **_k: False)
    monkeypatch.setattr(db, "_registered_all", True)
    monkeypatch.setattr(db, "_last_attempt", 0.0)
    db.remember_unregistered(pid)
    db.pool()
    assert db.wait_for_retry(10)
    assert {pid, newcomer} <= db._unregistered
    db._unregistered.difference_update({pid, newcomer})


@needs_database
def test_the_retry_pass_runs_in_the_background_never_in_the_caller(make_project, monkeypatch):
    """The retry pass ran inline in whichever request first called pool() after RETRY_SECONDS:
    with the dashboard down, that request (Caddy's forward_auth, or the relay holding a log's lock)
    waited the whole pass, 5 s per unregistered project."""
    import time

    from platform_service import dashboard_bridge

    pid = str(make_project()["pid"])
    db.pool()                                                         # the first setup is done

    def slow_register(*_args, **_kwargs):
        time.sleep(2.0)
        return True

    monkeypatch.setattr(dashboard_bridge, "register", slow_register)
    monkeypatch.setattr(db, "_registered_all", True)
    monkeypatch.setattr(db, "_last_attempt", 0.0)
    db.remember_unregistered(pid)
    t0 = time.monotonic()
    db.pool()
    waited = time.monotonic() - t0
    assert waited < 0.2, f"the caller of pool() ran the retry pass ({waited:.2f}s)"
    assert db.wait_for_retry(10), "the retry pass never ended"
    assert pid not in db._unregistered                                # the pass still did its work
