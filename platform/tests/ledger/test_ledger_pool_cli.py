"""The operator's pool command, end to end on a throwaway immudb. The superuser's
password is only in the command's own environment; the platform, as aisc_ledger, then takes one of the
databases and writes to it. This is what scripts/ledger-pool.sh runs."""
from __future__ import annotations

import os
import subprocess
import sys
import uuid

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


def _top_up(dsn, count):
    env = {**os.environ, "PLATFORM_DATABASE_URL": dsn, "LEDGER_IMMUDB_URL": IMMUDB_URL,
           "IMMUDB_ADMIN_PASSWORD": IMMUDB_ADMIN_PASSWORD, "LEDGER_IMMUDB_PASSWORD": LEDGER_USER_PASSWORD}
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
           "LEDGER_IMMUDB_PASSWORD": "y" * 12}
    started = time.monotonic()
    r = subprocess.run([sys.executable, "-m", "platform_service.ledger.pool", "top-up", "--wait", "3", "1"], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and time.monotonic() - started >= 3
    assert "waited 3 s" in r.stderr and "x" * 12 not in r.stdout + r.stderr
