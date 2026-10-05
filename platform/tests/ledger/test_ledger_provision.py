"""The pool of ledger databases.
Called directly, with no HTTP and no relay. The operator's
script pre-creates databases (the platform never holds the immudb superuser); `provision.assign(pid)`
takes a free one of the current store's server, inside the caller's transaction, and keeps it for ever.
Project creation, events waiting on an empty pool and the delete are in
test_ledger_provision_flow.py."""
from __future__ import annotations

import threading
import uuid

import pytest

from platform_service.ledger import pool, provision
from tests.ledger.conftest import needs_db

pytestmark = needs_db


def pid():
    return str(uuid.uuid4())


def test_assign_takes_a_database_of_the_current_store(memory_ledger):
    before = provision.pool_level()
    p = pid()
    db = provision.assign(p)
    assert db in memory_ledger.databases() and provision.database_for(p) == db
    assert provision.pool_level() == before - 1


def test_assigning_twice_gives_the_same_database(memory_ledger):
    p = pid()
    assert provision.assign(p) == provision.assign(p)


def test_two_projects_never_share_a_database_even_at_once(memory_ledger):
    pids, errors = [pid() for _ in range(6)], []

    def run(p):
        try:
            provision.assign(p)
        except Exception as exc:                                     # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=run, args=(p,)) for p in pids]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    assert len({provision.database_for(p) for p in pids}) == 6


def test_another_servers_pool_is_never_used(own_store):
    own_store(3)                                                    # a server with free databases
    own_store(0)                                                    # the current one has none
    assert provision.assign(pid()) is None


def test_with_the_pool_empty_a_project_waits_and_gets_one_after_a_refill(own_store):
    from platform_service.ledger import testing

    store = own_store(0)
    p = pid()
    assert provision.assign(p) is None and provision.database_for(p) is None
    testing.fill_pool(store, n=1)
    assert provision.assign_pending(p) is True
    assert provision.database_for(p) in store.databases()


def test_an_assignment_in_a_rolled_back_transaction_leaves_the_database_free(memory_ledger):
    """Project creation calls assign in its own transaction: a failed creation consumes nothing (n-c)."""
    before, p = provision.pool_level(), pid()
    with pytest.raises(RuntimeError):
        with provision.transaction() as conn:
            provision.assign(p, conn=conn)
            raise RuntimeError("the project insert failed")
    assert provision.pool_level() == before and provision.database_for(p) is None


@pytest.mark.parametrize("bad", ["defaultdb", "ledger", "LEDGER" + "a" * 32, "x;drop"])
def test_the_pool_refuses_a_name_that_is_not_a_ledger_name(memory_ledger, bad):
    with pytest.raises(ValueError):
        pool.register(memory_ledger, [bad])


def test_the_server_id_is_the_servers_own_identity(memory_ledger):
    """Not its address, which changes with a hostname (n-c): immudb's server UUID, `memory:<uuid>` here."""
    assert memory_ledger.server_id.startswith("memory:") and uuid.UUID(memory_ledger.server_id[7:])


def test_with_immudb_unreachable_assign_waits_and_never_blocks(memory_ledger):
    """Project creation must not depend on immudb being up. With the store unreachable,
    assign answers None (pending) quickly instead of raising or hanging."""
    import time

    from platform_service import ledger
    from platform_service.ledger.state import MemoryStateStore
    from platform_service.ledger.store import ImmudbLedger

    previous = ledger.use(ImmudbLedger("127.0.0.1:1", user="aisc_ledger", password="x",
                                       state_store=MemoryStateStore()))
    try:
        started = time.monotonic()
        assert provision.assign(pid()) is None
        assert time.monotonic() - started < 10
    finally:
        ledger.use(previous)


def test_migration_0006_says_what_is_missing_without_the_schema():
    """The guard: a platform migrating before postgres-setup made the schema gets a clear message."""
    import psycopg

    from tests.core_scratch import apply_platform_migrations, scratch_database

    from tests.ledger.conftest import SUPERUSER_DSN, need
    need(SUPERUSER_DSN, "PLATFORM_TEST_SUPERUSER_URL is not set")
    with scratch_database(old_layout=True) as (su, rw):
        with psycopg.connect(su, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS ledger CASCADE")
            conn.execute("ALTER TABLE core.system OWNER TO platform_rw")
        with pytest.raises(psycopg.errors.RaiseException, match="schema ledger is missing"):
            apply_platform_migrations(rw)
