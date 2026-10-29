"""The engine's own immudb account, on throwaway immudb 1.11.1 containers of
the tests' own (immudb_box), so each test starts from an empty server or a state it builds itself.

The engine's audit clerk (apps/backend/aisc_backend/audit/clerk.py, frozen) is replayed call for call: it
logs in WITHOUT naming a database, lists the databases, creates `auditdb` only when it is not listed,
switches to it and runs its own CREATE TABLE / INSERT / SELECT (read from its source here, so the SQL is
exactly the engine's) and the verifiedSet/verifiedGet probe of verify(). One test runs the engine's own
integration test, unchanged, as aisc_engine.

    LEDGER_TESTS_REQUIRED=1 scripts/test-platform.sh tests/ledger/test_engine_account.py
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.ledger.conftest import need
from tests.ledger.immudb_box import (ImmudbBox, databases, docker_available, logs_in, password, permissions,
                                     sql_grants)

ROOT = Path(__file__).resolve().parents[3]
CLERK = ROOT / "apps/backend/aisc_backend/audit/clerk.py"
R, RW = 1, 2                                     # immudb's PERMISSION_R, PERMISSION_RW


def _clerk_sql(name: str) -> str:
    tree = ast.parse(CLERK.read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in the engine's clerk")


CREATE_TABLE, INSERT = _clerk_sql("_CREATE_TABLE"), _clerk_sql("_INSERT")


@pytest.fixture
def box():
    need(docker_available(), "docker is not available for a throwaway immudb")
    b = ImmudbBox()
    yield b
    b.close()


class _EngineAccount:
    """platform_service.ledger.engine_account, imported when a test first uses it (so a missing module
    fails that test, not the collection)."""

    def __getattr__(self, name):
        from platform_service.ledger import engine_account

        return getattr(engine_account, name)


ea = _EngineAccount()


ENGINE_PW = password()


def clerk_connect(url: str, pw: str):
    """The clerk's connect(), as aisc_engine: login with no database, databaseList, useDatabase, CREATE."""
    from immudb import ImmudbClient

    c = ImmudbClient(url)
    c.login("aisc_engine", pw)
    listed = [d.decode() if isinstance(d, bytes) else d for d in c.databaseList()]
    assert "auditdb" in listed, f"the clerk would call createDatabase: auditdb not in {listed}"
    c.useDatabase(b"auditdb")
    c.sqlExec(CREATE_TABLE)
    return c


def clerk_write(c, marker: str = "probe") -> None:
    c.sqlExec(INSERT, params={"occurred_at": datetime.now(timezone.utc), "actor": "t", "action": "probe",
                              "resource_type": marker, "resource_id": "r", "source_app": "backend",
                              "source_ip": "1.2.3.4", "outcome": "ok", "metadata": "{}", "summary": "t probe"})


def clerk_rows(c) -> list:
    return list(c.sqlQuery("SELECT id, occurred_at, actor, action, resource_type, resource_id, source_app, "
                           "source_ip, outcome, metadata, summary FROM audit_log;"))


def clerk_verify(c) -> bool:
    c.verifiedSet(b"audit:_integrity_probe", b"ok")
    return c.verifiedGet(b"audit:_integrity_probe").value == b"ok"


def _state(box):
    admin = box.admin()
    return permissions(admin, ea.ENGINE_USER), sql_grants(admin, ea.ENGINE_USER, ea.ENGINE_DATABASE)


def _refused(fn) -> str:
    with pytest.raises(Exception) as exc:
        fn()
    return getattr(exc.value, "details", lambda: "")() or str(exc.value)


def test_names_are_the_ones_compose_uses():
    assert ea.ENGINE_USER == "aisc_engine" and ea.ENGINE_DATABASE == "auditdb"
    assert set(ea.ENGINE_SQL_PRIVILEGES) == {"SELECT", "CREATE", "INSERT"}


def test_on_an_empty_immudb_it_makes_the_database_the_user_and_exactly_its_rights(box):
    assert "auditdb" not in databases(box.admin())
    assert ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW) != "unchanged"
    assert "auditdb" in databases(box.admin())
    perms, grants = _state(box)
    assert perms == {"defaultdb": R, "auditdb": RW}, perms
    assert grants == {"SELECT", "CREATE", "INSERT"}, grants


def test_the_clerks_exact_sequence_works_as_aisc_engine(box):
    ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW)
    c = clerk_connect(box.url, ENGINE_PW)
    c.sqlExec(CREATE_TABLE)                                   # its CREATE TABLE IF NOT EXISTS, a second time
    clerk_write(c, "s1_2")
    rows = clerk_rows(c)
    assert [r for r in rows if r[4] == "s1_2"], rows
    assert clerk_verify(c) is True


def test_everything_beyond_its_audit_log_is_refused(box):
    from immudb import ImmudbClient, constants
    from immudb.datatypesv2 import DatabaseSettingsV2

    from platform_service.ledger import pool
    from platform_service.ledger.naming import PLATFORM_DB, pool_name

    ledger_db = pool_name()
    pool.create_databases(box.url, admin_password=box.admin_password, names=[ledger_db, PLATFORM_DB],
                          grantee="aisc_ledger", grantee_password=password())
    admin = box.admin()
    admin.sqlExec("CREATE TABLE IF NOT EXISTS superset_audit (id INTEGER AUTO_INCREMENT, a VARCHAR, PRIMARY KEY id)")
    admin.sqlExec("INSERT INTO superset_audit (a) VALUES ('marker')")
    ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW)
    c = clerk_connect(box.url, ENGINE_PW)
    clerk_write(c)

    _refused(lambda: c.createDatabase(b"other"))
    _refused(lambda: c.createDatabaseV2("other2", DatabaseSettingsV2(), True))
    for db in (ledger_db, PLATFORM_DB):
        _refused(lambda: c.useDatabase(db.encode()))
        assert not logs_in(box.url, "aisc_engine", ENGINE_PW, database=db), f"aisc_engine logged in to {db}"
    d = ImmudbClient(box.url)
    d.login("aisc_engine", ENGINE_PW)                           # defaultdb, read only
    _refused(lambda: list(d.sqlQuery("SELECT a FROM superset_audit")))
    _refused(lambda: d.set(b"k", b"v"))
    c.useDatabase(b"auditdb")
    _refused(lambda: c.sqlExec("DELETE FROM audit_log WHERE id > 0"))
    _refused(lambda: c.sqlExec("DROP TABLE audit_log"))
    _refused(lambda: c.createUser("intruder", password(), constants.PERMISSION_RW, "auditdb"))
    _refused(lambda: c.changePermission(constants.PERMISSION_GRANT, "aisc_engine", "defaultdb", constants.PERMISSION_RW))
    assert len(clerk_rows(c)) == 1, "a refused statement changed the audit log"


def test_a_second_call_changes_nothing_and_calls_no_change_permission(box, monkeypatch):
    from immudb import ImmudbClient

    ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW)
    before = _state(box)
    session = clerk_connect(box.url, ENGINE_PW)                 # an engine running while ledger-pool re-runs
    clerk_write(session, "before")
    calls = []
    real = ImmudbClient.changePermission
    monkeypatch.setattr(ImmudbClient, "changePermission", lambda self, *a, **k: calls.append(a) or real(self, *a, **k))
    assert ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW) == "unchanged"
    assert calls == [], f"a re-run called changePermission {len(calls)} times"
    assert _state(box) == before
    clerk_write(session, "after")                               # the open session keeps its privileges
    assert {r[4] for r in clerk_rows(session)} >= {"before", "after"}


def test_upgrade_of_an_auditdb_the_superuser_made(box):
    admin = box.admin()
    admin.createDatabase(b"auditdb")                            # the clerk's legacy path, as the superuser
    admin.useDatabase(b"auditdb")
    admin.sqlExec(CREATE_TABLE)
    for i in range(3):
        clerk_write(admin, f"legacy{i}")
    admin.verifiedSet(b"audit:_integrity_probe", b"ok")
    assert ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW) != "unchanged"
    c = clerk_connect(box.url, ENGINE_PW)
    legacy = {r[4] for r in clerk_rows(c)}
    assert legacy == {"legacy0", "legacy1", "legacy2"}, legacy
    clerk_write(c, "new")
    assert clerk_verify(c) is True
    assert len(clerk_rows(c)) == 4


@pytest.mark.parametrize("damage", ["wiped", "all_seven"])
def test_a_damaged_account_is_repaired_by_one_call(box, damage):
    from immudb import constants

    ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW)
    admin = box.admin()
    if damage == "wiped":                                       # a later grant wipes SQL privileges elsewhere
        admin.changePermission(constants.PERMISSION_GRANT, "aisc_engine", "defaultdb", constants.PERMISSION_R)
        assert sql_grants(box.admin(), "aisc_engine") == set()
    else:                                                       # a fresh grant on auditdb gives all seven
        admin.changePermission(constants.PERMISSION_GRANT, "aisc_engine", "auditdb", constants.PERMISSION_RW)
        assert len(sql_grants(box.admin(), "aisc_engine")) == 7
    assert ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW) != "unchanged"
    assert _state(box) == ({"defaultdb": R, "auditdb": RW}, {"SELECT", "CREATE", "INSERT"})
    clerk_write(clerk_connect(box.url, ENGINE_PW))


def test_a_user_left_without_auditdb_and_with_another_password_is_brought_to_the_design(box):
    """aisc_engine exists (made by hand, or auditdb lost) with another password and no auditdb:
    one call makes the database, repairs the rights AND gives it ENGINE_IMMUDB_PASSWORD (making the
    database must not skip the password step)."""
    from immudb import constants

    box.admin().createUser("aisc_engine", password(), constants.PERMISSION_R, "defaultdb")
    assert ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW) != "unchanged"
    assert _state(box) == ({"defaultdb": R, "auditdb": RW}, {"SELECT", "CREATE", "INSERT"})
    clerk_write(clerk_connect(box.url, ENGINE_PW))


def test_it_never_deletes_a_database_or_a_user(box):
    from immudb import constants
    from immudb.datatypesv2 import DatabaseSettingsV2

    admin = box.admin()
    admin.createDatabaseV2("keepme", DatabaseSettingsV2(), True)
    admin.createUser("someone", password(), constants.PERMISSION_R, "keepme")
    dbs = databases(admin)
    users = {u.user for u in admin.listUsers().userlist.users}
    for _ in range(2):
        ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW)
        admin = box.admin()
        assert databases(admin) >= dbs
        assert {u.user for u in admin.listUsers().userlist.users} >= users


def test_the_engines_own_integration_test_passes_as_aisc_engine(box, tmp_path):
    """The frozen clerk, unchanged: apps/backend's test_immudb_integration with the engine account's
    environment and NO superuser password. It skips silently when its login fails, so 2 tests and no
    skip are required."""
    backend = ROOT / "apps/backend"
    python = backend / ".venv/bin/python"
    need(python.exists(), "apps/backend/.venv is missing (uv sync in apps/backend)")
    ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("IMMUDB_", "DJANGO_SETTINGS"))}
    env.update({"IMMUDB_URL": box.url, "IMMUDB_USER": "aisc_engine", "IMMUDB_PASSWORD": ENGINE_PW,
                "IMMUDB_DATABASE": "auditdb",
                "PYTHONPATH": f"{ROOT}/shared/plugin-interface/src:{ROOT}/shared/plugin-manager/src:{ROOT}/shared/identity",
                "DB_ENGINE": "django.db.backends.sqlite3", "DB_NAME": str(tmp_path / "e.db")})
    r = subprocess.run([str(python), "manage.py", "test", "aisc_backend.tests.integration.test_immudb_integration",
                        "-v", "2"], cwd=backend, env=env, capture_output=True, text=True, timeout=600)
    out = r.stdout + r.stderr
    assert ENGINE_PW not in out
    assert r.returncode == 0, out[-3000:]
    assert "Ran 2 tests" in out and "skipped" not in out, out[-3000:]


def _check(url: str, pw: str):
    env = {**os.environ, "LEDGER_IMMUDB_URL": url, "ENGINE_IMMUDB_PASSWORD": pw}
    env.pop("IMMUDB_ADMIN_PASSWORD", None)
    return subprocess.run([sys.executable, "-m", "platform_service.ledger.engine_account", "check"], env=env,
                          capture_output=True, text=True, timeout=120)


def test_check_passes_on_the_made_account(box):
    ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW)
    r = _check(box.url, ENGINE_PW)
    assert r.returncode == 0, r.stdout + r.stderr
    assert ENGINE_PW not in r.stdout + r.stderr and box.admin_password not in r.stdout + r.stderr


def test_check_names_each_problem(box):
    from immudb import constants
    from immudb.datatypesv2 import DatabaseSettingsV2

    ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW)
    wrong = password()
    r = _check(box.url, wrong)
    assert r.returncode == 1 and "password" in (r.stdout + r.stderr).lower(), r.stdout + r.stderr
    assert wrong not in r.stdout + r.stderr

    admin = box.admin()                                          # privileges reset to all seven
    admin.changePermission(constants.PERMISSION_GRANT, "aisc_engine", "auditdb", constants.PERMISSION_RW)
    r = _check(box.url, ENGINE_PW)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and ("DELETE" in out or "DROP" in out), out

    ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW)
    admin = box.admin()
    admin.createDatabaseV2("thirddb", DatabaseSettingsV2(), True)
    admin.changePermission(constants.PERMISSION_GRANT, "aisc_engine", "thirddb", constants.PERMISSION_R)
    ea.ensure(box.url, admin_password=box.admin_password, password=ENGINE_PW)  # SQL back
    r = _check(box.url, ENGINE_PW)
    assert r.returncode == 1 and "thirddb" in r.stdout + r.stderr, r.stdout + r.stderr
    assert ENGINE_PW not in r.stdout + r.stderr
