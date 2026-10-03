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


def test_the_pool_command_makes_databases_the_platform_can_use(dsn):
    from platform_service import ledger
    from platform_service.ledger import provision
    from platform_service.ledger.state import MemoryStateStore
    from platform_service.ledger.store import ImmudbLedger

    need(IMMUDB_URL and IMMUDB_ADMIN_PASSWORD, "LEDGER_TEST_IMMUDB_URL / LEDGER_TEST_IMMUDB_ADMIN_PASSWORD are not set")
    env = {**os.environ, "PLATFORM_DATABASE_URL": dsn, "LEDGER_IMMUDB_URL": IMMUDB_URL,
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


def test_the_pool_command_refuses_without_the_superuser_password(dsn):
    env = {k: v for k, v in os.environ.items() if k != "IMMUDB_ADMIN_PASSWORD"}
    env.update({"PLATFORM_DATABASE_URL": dsn, "LEDGER_IMMUDB_URL": IMMUDB_URL or "127.0.0.1:1",
                "LEDGER_IMMUDB_PASSWORD": LEDGER_USER_PASSWORD})
    r = subprocess.run([sys.executable, "-m", "platform_service.ledger.pool", "create", "1"], env=env,
                       capture_output=True, text=True, timeout=60)
    assert r.returncode != 0 and "IMMUDB_ADMIN_PASSWORD" in r.stderr
