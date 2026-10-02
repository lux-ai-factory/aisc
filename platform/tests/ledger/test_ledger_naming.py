"""L2: ledger database names (I9; spec 6.1, 7.1). immudb can't rename a database, and the operator's pool
makes databases before any project exists, so a name never carries a pid (second review N1): it is
random, and a project's log is found through `provision.database_for(pid)`. A name is checked before
any immudb call, so nothing else ever reaches immudb as a database name."""
from __future__ import annotations

import pytest

from platform_service.ledger.naming import PLATFORM_DB, is_ledger_name, pool_name


def test_a_pool_name_is_ledger_and_32_random_hex():
    names = {pool_name() for _ in range(200)}
    assert len(names) == 200
    assert all(len(n) == 38 and n.startswith("ledger") and int(n[6:], 16) >= 0 for n in names)
    assert all(n == n.lower() for n in names)


def test_the_platforms_own_events_have_their_own_database():
    assert PLATFORM_DB == "ledgerplatform" and is_ledger_name(PLATFORM_DB)


def test_a_pool_name_is_a_ledger_name():
    assert is_ledger_name(pool_name())


@pytest.mark.parametrize("bad", ["", "mcas", "defaultdb", "systemdb", "../x", "ledger", "ledger" + "g" * 32,
                                 "LEDGER" + "a" * 32, "ledger" + "a" * 31, "ledger" + "a" * 33,
                                 "ledger" + "a" * 32 + ";drop", None])
def test_anything_else_is_not(bad):
    assert not is_ledger_name(bad)
