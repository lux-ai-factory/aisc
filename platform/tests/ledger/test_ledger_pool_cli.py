"""The operator's pool command, end to end on a throwaway immudb. The superuser's
password is only in the command's own environment; the platform, as aisc_ledger, then takes one of the
databases and writes to it. This is what scripts/ledger-pool.sh runs."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import uuid

import pytest

from tests.ledger.conftest import (IMMUDB_ADMIN_PASSWORD, IMMUDB_URL, LEDGER_USER_PASSWORD, MADE, need, needs_db)

pytestmark = needs_db


def test_the_pool_command_makes_databases_the_platform_can_use(platform_dsn):
    from platform_service import ledger
    from platform_service.ledger import provision
    from platform_service.ledger.state import MemoryStateStore
    from platform_service.ledger.store import ImmudbLedger

    need(IMMUDB_URL and IMMUDB_ADMIN_PASSWORD, "LEDGER_TEST_IMMUDB_URL / LEDGER_TEST_IMMUDB_ADMIN_PASSWORD are not set")
    env = {**os.environ, "PLATFORM_DATABASE_URL": platform_dsn, "LEDGER_IMMUDB_URL": IMMUDB_URL,
           "IMMUDB_ADMIN_PASSWORD": IMMUDB_ADMIN_PASSWORD, "LEDGER_IMMUDB_PASSWORD": LEDGER_USER_PASSWORD}
    r = subprocess.run([sys.executable, "-m", "platform_service.ledger.pool", "create", "2"], env=env,
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    assert IMMUDB_ADMIN_PASSWORD not in r.stdout + r.stderr                # never echoed
    store = ImmudbLedger(IMMUDB_URL, user="aisc_ledger", password=LEDGER_USER_PASSWORD,
                         state_store=MemoryStateStore())
    MADE["servers"].add(store.server_id)
    previous = ledger.use(store)
    try:
        pid = str(uuid.uuid4())
        db = provision.assign(pid)
        assert db is not None and db in store.databases()
        assert store.append(db, {"event_id": str(uuid.uuid4()), "action": "risk.rated"}) == 1
    finally:
        ledger.use(previous)


def test_the_pool_command_refuses_without_the_superuser_password(platform_dsn):
    env = {k: v for k, v in os.environ.items() if k != "IMMUDB_ADMIN_PASSWORD"}
    env.update({"PLATFORM_DATABASE_URL": platform_dsn, "LEDGER_IMMUDB_URL": IMMUDB_URL or "127.0.0.1:1",
                "LEDGER_IMMUDB_PASSWORD": LEDGER_USER_PASSWORD})
    r = subprocess.run([sys.executable, "-m", "platform_service.ledger.pool", "create", "1"], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "IMMUDB_ADMIN_PASSWORD" in r.stderr


#: aisc_engine's password on the shared throwaway immudb: top-up makes that account too.
ENGINE_USER_PASSWORD = "Engine-test-pw-123!"


def _top_up(dsn, count):
    env = {**os.environ, "PLATFORM_DATABASE_URL": dsn, "LEDGER_IMMUDB_URL": IMMUDB_URL,
           "IMMUDB_ADMIN_PASSWORD": IMMUDB_ADMIN_PASSWORD, "LEDGER_IMMUDB_PASSWORD": LEDGER_USER_PASSWORD,
           "ENGINE_IMMUDB_PASSWORD": ENGINE_USER_PASSWORD}
    r = subprocess.run([sys.executable, "-m", "platform_service.ledger.pool", "top-up", str(count)], env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    assert IMMUDB_ADMIN_PASSWORD not in r.stdout + r.stderr
    return r.stdout


def _free(dsn, server_id):
    import psycopg

    with psycopg.connect(dsn) as conn:
        return conn.execute("SELECT count(*) FROM ledger.pool WHERE assigned_pid IS NULL AND server_id = %s",
                            (server_id,)).fetchone()[0]


def _server_id():
    from platform_service.ledger.state import MemoryStateStore
    from platform_service.ledger.store import ImmudbLedger

    store = ImmudbLedger(IMMUDB_URL, user="aisc_ledger", password=LEDGER_USER_PASSWORD, state_store=MemoryStateStore())
    MADE["servers"].add(store.server_id)
    return store.server_id


def test_top_up_keeps_the_pool_at_its_level_and_makes_nothing_more(platform_dsn):
    """What the ledger-pool service runs at every start: the pool is brought up to N free databases;
    a second run with the pool full makes none."""
    need(IMMUDB_URL and IMMUDB_ADMIN_PASSWORD, "LEDGER_TEST_IMMUDB_URL / LEDGER_TEST_IMMUDB_ADMIN_PASSWORD are not set")
    _top_up(platform_dsn, 0)                                                     # (the server's identity, first)
    server = _server_id()
    level = _free(platform_dsn, server) + 2
    _top_up(platform_dsn, level)
    assert _free(platform_dsn, server) == level
    out = _top_up(platform_dsn, level)
    assert _free(platform_dsn, server) == level and "made 0" in out


def test_top_up_gives_a_waiting_project_its_database(platform_dsn):
    """A project created while the pool was empty waits for its ledger database: the next top-up gives it
    one, and its events can then be delivered."""
    import psycopg

    from platform_service.ledger import provision

    need(IMMUDB_URL and IMMUDB_ADMIN_PASSWORD, "LEDGER_TEST_IMMUDB_URL / LEDGER_TEST_IMMUDB_ADMIN_PASSWORD are not set")
    _top_up(platform_dsn, 0)
    pid = str(uuid.uuid4())
    with psycopg.connect(platform_dsn) as conn:
        conn.execute("INSERT INTO core.project (pid, name, slug) VALUES (%s, %s, %s)",
                     (pid, f"waiting {pid[:8]}", f"pytest-waiting-{pid[:8]}"))
    try:
        assert provision.database_for(pid) is None
        _top_up(platform_dsn, _free(platform_dsn, _server_id()) + 1)
        assert provision.database_for(pid) is not None
    finally:
        with psycopg.connect(platform_dsn) as conn:
            conn.execute("DELETE FROM core.project WHERE pid = %s", (pid,))


def test_top_up_waits_for_the_platform_and_gives_up_with_a_reason():
    """At a stack's first start the one-shot can run before the platform has migrated ledger.pool, or
    before immudb answers: it retries for --wait seconds, then fails saying what it waited for."""
    import time

    env = {**os.environ, "PLATFORM_DATABASE_URL": "postgresql://nobody:x@127.0.0.1:1/platform",
           "LEDGER_IMMUDB_URL": IMMUDB_URL or "127.0.0.1:1", "IMMUDB_ADMIN_PASSWORD": "x" * 12,
           "LEDGER_IMMUDB_PASSWORD": "y" * 12, "ENGINE_IMMUDB_PASSWORD": "z" * 12}
    started = time.monotonic()
    r = subprocess.run([sys.executable, "-m", "platform_service.ledger.pool", "top-up", "--wait", "3", "1"], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and time.monotonic() - started >= 3
    assert "waited 3 s" in r.stderr and not any(s in r.stdout + r.stderr for s in ("x" * 12, "y" * 12, "z" * 12))


# The engine's account. Tests that need an empty server use one of
# their own (immudb_box); the others use the shared throwaway immudb.

def _env(dsn, url, admin, engine=ENGINE_USER_PASSWORD, ledger=LEDGER_USER_PASSWORD):
    env = {k: v for k, v in os.environ.items() if k not in ("IMMUDB_ADMIN_PASSWORD", "ENGINE_IMMUDB_PASSWORD")}
    env.update({"PLATFORM_DATABASE_URL": dsn, "LEDGER_IMMUDB_URL": url, "IMMUDB_ADMIN_PASSWORD": admin,
                "LEDGER_IMMUDB_PASSWORD": ledger})
    if engine is not None:
        env["ENGINE_IMMUDB_PASSWORD"] = engine
    return env


def _pool(env, *args, timeout=180):
    return subprocess.run([sys.executable, "-m", "platform_service.ledger.pool", *args], env=env,
                          capture_output=True, text=True, timeout=timeout)


@pytest.fixture
def box():
    from tests.ledger.immudb_box import ImmudbBox, docker_available

    need(docker_available(), "docker is not available for a throwaway immudb")
    b = ImmudbBox()
    yield b
    b.close()


UNREACHABLE = "postgresql://nobody:x@127.0.0.1:1/platform"


def test_top_up_without_the_engine_password_exits_2_and_makes_nothing(box):
    from tests.ledger.immudb_box import databases, permissions

    r = _pool(_env(UNREACHABLE, box.url, box.admin_password, engine=None), "top-up", "--wait", "2", "1")
    assert r.returncode == 2, r.stdout + r.stderr
    assert "ENGINE_IMMUDB_PASSWORD" in r.stderr
    admin = box.admin()
    assert "auditdb" not in databases(admin) and permissions(admin, "aisc_engine") is None


def test_the_engine_account_is_made_before_the_wait_for_the_platform(box):
    from tests.ledger.immudb_box import permissions, sql_grants

    r = _pool(_env(UNREACHABLE, box.url, box.admin_password), "top-up", "--wait", "3", "1", timeout=120)
    out = r.stdout + r.stderr
    assert r.returncode == 3, out
    assert "waited 3 s" in r.stderr
    admin = box.admin()
    assert permissions(admin, "aisc_engine") == {"defaultdb": 1, "auditdb": 2}
    assert sql_grants(admin, "aisc_engine") == {"SELECT", "CREATE", "INSERT"}
    for secret in (box.admin_password, ENGINE_USER_PASSWORD, LEDGER_USER_PASSWORD):
        assert secret not in out


def test_top_up_makes_the_account_and_a_second_run_says_unchanged(platform_dsn):
    need(IMMUDB_URL and IMMUDB_ADMIN_PASSWORD, "LEDGER_TEST_IMMUDB_URL / LEDGER_TEST_IMMUDB_ADMIN_PASSWORD are not set")
    first = _top_up(platform_dsn, 0)
    assert re.search(r"engine account aisc_engine on auditdb: (made|unchanged)", first), first
    second = _top_up(platform_dsn, 0)
    assert "engine account aisc_engine on auditdb: unchanged" in second, second
    _server_id()


def test_no_output_holds_a_password(platform_dsn):
    need(IMMUDB_URL and IMMUDB_ADMIN_PASSWORD, "LEDGER_TEST_IMMUDB_URL / LEDGER_TEST_IMMUDB_ADMIN_PASSWORD are not set")
    r = _pool(_env(platform_dsn, IMMUDB_URL, IMMUDB_ADMIN_PASSWORD), "top-up", "0")
    assert r.returncode == 0, r.stderr[-2000:]
    assert "engine account aisc_engine" in r.stdout
    out = r.stdout + r.stderr
    for secret in (IMMUDB_ADMIN_PASSWORD, ENGINE_USER_PASSWORD, LEDGER_USER_PASSWORD):
        assert secret not in out
    env = {**os.environ, "LEDGER_IMMUDB_URL": IMMUDB_URL, "ENGINE_IMMUDB_PASSWORD": ENGINE_USER_PASSWORD}
    c = subprocess.run([sys.executable, "-m", "platform_service.ledger.engine_account", "check"], env=env,
                       capture_output=True, text=True, timeout=120)
    assert c.returncode == 0, c.stdout + c.stderr
    assert ENGINE_USER_PASSWORD not in c.stdout + c.stderr


def test_pool_create_needs_no_engine_password(platform_dsn):
    """The operator's script hands the platform container only the superuser's and the ledger user's
    passwords (scripts/ledger-pool.sh): `create` must keep working without ENGINE_IMMUDB_PASSWORD."""
    need(IMMUDB_URL and IMMUDB_ADMIN_PASSWORD, "LEDGER_TEST_IMMUDB_URL / LEDGER_TEST_IMMUDB_ADMIN_PASSWORD are not set")
    r = _pool(_env(platform_dsn, IMMUDB_URL, IMMUDB_ADMIN_PASSWORD, engine=None), "create", "1")
    assert r.returncode == 0, r.stdout + r.stderr
    _server_id()
