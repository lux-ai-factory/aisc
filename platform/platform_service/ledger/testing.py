"""Helpers for the ledger's own tests (spec 6.1). Never used by the service."""
from __future__ import annotations

from platform_service.ledger import pool
from platform_service.ledger.naming import PLATFORM_DB, pool_name


def fill_pool(store, n: int) -> list[str]:
    """Make `n` databases (and the platform log) in a memory store and register them, as the operator's
    script does for immudb."""
    if not hasattr(store, "create"):
        raise TypeError("fill_pool makes databases in a MemoryLedger; use scripts/ledger-pool.sh for immudb")
    names = [pool_name() for _ in range(n)]
    for name in names + [PLATFORM_DB]:
        store.create(name)
    pool.register(store, names)
    return names
