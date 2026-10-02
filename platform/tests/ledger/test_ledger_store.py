"""L4: the store (I3, I4, I9, T8, T11, T21, T24; spec 6.1, 7.1-7.3). Each contract test runs on the
memory store and on a throwaway immudb 1.11.1 as `aisc_ledger` (never the superuser), each test on
databases of its own (R4.4). The immudb-only tests reproduce what the spike saw (06-spike.md M1-M15)."""
from __future__ import annotations

import threading
import uuid

import pytest

from platform_service.ledger.state import MemoryStateStore
from platform_service.ledger.store import (DuplicateEvent, EntryTooLarge, ImmudbLedger, MemoryLedger, TamperAlarm,
                                           UnknownDatabase)
from tests.ledger.conftest import (IMMUDB_ADMIN_PASSWORD, IMMUDB_URL, LEDGER_USER_PASSWORD, fresh_databases,
                                   need)


def entry(**over):
    base = {"event_id": str(uuid.uuid4()), "action": "risk.rated", "item_type": "risk", "item_id": "risk2",
            "actor_kind": "user", "actor_ref": "actor:" + "1" * 32, "source_app": "control_objectives",
            "details": {"impact": 5}}
    base.update(over)
    return base


# the contract, on both stores -----------------------------------------------------------------------

def test_appending_gives_increasing_numbers(any_store):
    store, (a, _) = any_store
    first, second = store.append(a, entry()), store.append(a, entry())
    assert second > first >= 1
    assert store.head(a).seq == second


def test_the_same_event_twice_is_recorded_once(any_store):
    store, (a, _) = any_store
    e = entry()
    seq = store.append(a, e)
    assert store.append(a, dict(e)) == seq
    assert [x.event_id for x in store.scan(a, after_seq=0, limit=100)] == [e["event_id"]]


def test_the_same_event_id_with_other_content_is_refused(any_store):
    store, (a, _) = any_store
    e = entry()
    store.append(a, e)
    with pytest.raises(DuplicateEvent):
        store.append(a, {**e, "item_id": "risk9"})


def test_an_entry_reads_back_as_it_was_written(any_store):
    store, (a, _) = any_store
    e = entry(details={"impact": 5, "note": "é ✓"})
    got = store.get(a, store.append(a, e))
    assert (got.event_id, got.action, got.actor_ref, got.details) == (e["event_id"], "risk.rated", e["actor_ref"],
                                                                       {"impact": 5, "note": "é ✓"})
    assert got.recorded_at is not None


def test_scan_is_in_order_and_paged(any_store):
    store, (a, _) = any_store
    seqs = [store.append(a, entry()) for _ in range(5)]
    assert [x.seq for x in store.scan(a, after_seq=0, limit=3)] == seqs[:3]
    assert [x.seq for x in store.scan(a, after_seq=seqs[2], limit=10)] == seqs[3:]


def test_one_projects_entries_never_show_in_anothers(any_store):
    store, (a, b) = any_store
    store.append(a, entry())
    assert store.scan(b, after_seq=0, limit=10) == []


def test_the_head_only_moves_forward(any_store):
    store, (a, _) = any_store
    store.append(a, entry())
    h1 = store.head(a)
    store.append(a, entry())
    h2 = store.head(a)
    assert h2.seq > h1.seq and h2.state_hash != h1.state_hash


def test_a_database_the_pool_never_made_is_refused(any_store):
    store, _ = any_store
    with pytest.raises(UnknownDatabase):
        store.append("ledger" + uuid.uuid4().hex, entry())


def test_an_entry_over_the_cap_is_refused(any_store, settings):
    store, (a, _) = any_store
    with pytest.raises(EntryTooLarge):
        store.append(a, entry(details={"note": "x" * settings.MAX_ENTRY_BYTES}))


def test_an_entry_just_under_the_cap_round_trips(any_store, settings):
    store, (a, _) = any_store
    note = "x" * (settings.MAX_ENTRY_BYTES - 2048)
    assert store.get(a, store.append(a, entry(details={"note": note}))).details["note"] == note


def test_two_threads_on_two_databases_never_cross(any_store):
    """The spike's shared client put 18% of entries in the wrong database, without an error (M9)."""
    store, (a, b) = any_store
    errors = []

    def write(db, n=250):
        try:
            for i in range(n):
                store.append(db, entry(item_id=f"{db}-{i}"))
        except Exception as exc:                                    # pragma: no cover - reported below
            errors.append(exc)
    threads = [threading.Thread(target=write, args=(db,)) for db in (a, b)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    for db in (a, b):
        items = [x.item_id for x in store.scan(db, after_seq=0, limit=1000)]
        assert len(items) == 250 and all(i.startswith(db) for i in items)


def test_a_rolled_back_state_raises_the_alarm(any_store):
    """The verified state the platform keeps claims more than the server holds: a restore (M13)."""
    store, (a, _) = any_store
    seq = store.append(a, entry())
    state = store.state(a)
    store.set_state(a, state.claiming(tx_id=state.tx_id + 1_000_000))   # test hook
    with pytest.raises(TamperAlarm):
        store.get(a, seq)


# memory only: tampering with storage ----------------------------------------------------------------

def test_a_changed_entry_raises_the_alarm():
    store = MemoryLedger()
    a = "ledger" + uuid.uuid4().hex
    store.create(a)
    seq = store.append(a, entry())
    store.tamper(a, seq, "actor_ref", "actor:" + "f" * 32)          # what someone with storage access could do
    with pytest.raises(TamperAlarm):
        store.get(a, seq)


# immudb only: what the spike saw --------------------------------------------------------------------

@pytest.fixture
def immudb():
    need(IMMUDB_URL and IMMUDB_ADMIN_PASSWORD,
         "LEDGER_TEST_IMMUDB_URL / LEDGER_TEST_IMMUDB_ADMIN_PASSWORD are not set (a throwaway immudb 1.11.1)")
    return lambda state=None: ImmudbLedger(IMMUDB_URL, user="aisc_ledger", password=LEDGER_USER_PASSWORD,
                                           state_store=state or MemoryStateStore())


def test_the_ledger_user_cannot_create_a_database(immudb):
    from platform_service.ledger import pool

    with pytest.raises(PermissionError):
        pool.create_databases(IMMUDB_URL, admin_user="aisc_ledger", admin_password=LEDGER_USER_PASSWORD,
                              names=["ledger" + uuid.uuid4().hex], grantee="aisc_ledger",
                              grantee_password=LEDGER_USER_PASSWORD)


def test_a_database_granted_after_login_is_usable(immudb):
    store = immudb()
    [a] = fresh_databases(1)
    store.append(a, entry())
    [b] = fresh_databases(1)                                        # granted after the store logged in (M7)
    assert store.append(b, entry()) >= 1


def test_the_state_survives_a_new_store_and_a_rollback_is_caught_by_it(immudb):
    """The state lives outside immudb (Postgres in production) and is keyed by database only (M11)."""
    state = MemoryStateStore()
    [a] = fresh_databases(1)
    seq = immudb(state).append(a, entry())
    assert immudb(state).get(a, seq).seq == seq
    saved = state.get(a)
    state.put(a, saved.claiming(tx_id=saved.tx_id + 50), expected=saved)
    with pytest.raises(TamperAlarm):
        immudb(state).get(a, seq)


def test_the_state_store_is_compare_and_set(immudb):
    state = MemoryStateStore()
    [a] = fresh_databases(1)
    immudb(state).append(a, entry())
    current = state.get(a)
    with pytest.raises(ValueError):
        state.put(a, current, expected=current.claiming(tx_id=current.tx_id - 1))


def test_the_pool_refuses_when_the_ledger_users_password_is_not_the_one_given(immudb):
    """An existing aisc_ledger with another password would make a pool the platform can't use: the
    operator's command checks the login and says so (found by the phase-1 drill)."""
    from platform_service.ledger import pool
    from platform_service.ledger.naming import pool_name

    fresh_databases(1)                                              # aisc_ledger exists, with the test password
    with pytest.raises(PermissionError, match="LEDGER_IMMUDB_PASSWORD"):
        pool.create_databases(IMMUDB_URL, admin_password=IMMUDB_ADMIN_PASSWORD, names=[pool_name()],
                              grantee="aisc_ledger", grantee_password="not-the-password")


def test_a_wrong_password_is_a_credentials_error_not_an_unknown_database(immudb):
    from platform_service.ledger.store import LedgerCredentials

    [a] = fresh_databases(1)
    wrong = ImmudbLedger(IMMUDB_URL, user="aisc_ledger", password="not-the-password", state_store=MemoryStateStore())
    with pytest.raises(LedgerCredentials):
        wrong.append(a, entry())


def test_the_ledger_user_sees_its_server_and_its_databases(immudb):
    """As aisc_ledger, which has no right on immudb's defaultdb: the server id needs no login, and the
    database list logs in to the platform log, which the pool command always makes (found by the
    phase-1 drill)."""
    from platform_service.ledger import pool
    from platform_service.ledger.naming import PLATFORM_DB

    pool.create_databases(IMMUDB_URL, admin_password=IMMUDB_ADMIN_PASSWORD, names=[PLATFORM_DB],
                          grantee="aisc_ledger", grantee_password=LEDGER_USER_PASSWORD)
    [a] = fresh_databases(1)
    store = immudb()
    assert store.server_id.startswith("immudb:") and len(store.server_id) > len("immudb:")
    assert {a, PLATFORM_DB} <= store.databases()
