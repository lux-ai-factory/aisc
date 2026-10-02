"""L4: the store (I3, I4, I9, T8, T11). Each test runs on the memory store and on a throwaway immudb."""
from __future__ import annotations

import json
import uuid

import pytest

from platform_service.ledger.store import MemoryLedger, TamperAlarm

A = "ledger" + "a" * 32
B = "ledger" + "b" * 32


def entry(**over):
    base = {"event_id": str(uuid.uuid4()), "action": "risk.rated", "item_type": "risk", "item_id": "risk2",
            "actor_kind": "user", "actor_sub": "sub-1", "actor_name": "alice", "source_app": "control_objectives",
            "details": {"impact": 5}}
    base.update(over)
    return base


def test_appending_gives_increasing_numbers(any_store):
    any_store.ensure(A)
    first, second = any_store.append(A, entry()), any_store.append(A, entry())
    assert second > first >= 1
    assert any_store.head(A).seq == second


def test_the_same_event_twice_is_recorded_once(any_store):
    any_store.ensure(A)
    e = entry()
    seq = any_store.append(A, e)
    assert any_store.append(A, dict(e)) == seq
    assert [x.event_id for x in any_store.scan(A, after_seq=0, limit=100)] == [e["event_id"]]


def test_an_entry_reads_back_as_it_was_written(any_store):
    any_store.ensure(A)
    e = entry(details={"impact": 5, "note": "é ✓"})
    got = any_store.get(A, any_store.append(A, e))
    assert (got.event_id, got.action, got.actor_sub, got.details) == (e["event_id"], "risk.rated", "sub-1",
                                                                       {"impact": 5, "note": "é ✓"})
    assert got.recorded_at is not None


def test_scan_is_in_order_and_paged(any_store):
    any_store.ensure(A)
    seqs = [any_store.append(A, entry()) for _ in range(5)]
    assert [x.seq for x in any_store.scan(A, after_seq=0, limit=3)] == seqs[:3]
    assert [x.seq for x in any_store.scan(A, after_seq=seqs[2], limit=10)] == seqs[3:]


def test_one_projects_entries_never_show_in_anothers(any_store):
    any_store.ensure(A)
    any_store.ensure(B)
    any_store.append(A, entry())
    assert any_store.scan(B, after_seq=0, limit=10) == []


def test_ensure_is_safe_to_repeat(any_store):
    any_store.ensure(A)
    seq = any_store.append(A, entry())
    any_store.ensure(A)
    assert any_store.head(A).seq == seq


def test_the_head_only_moves_forward(any_store):
    any_store.ensure(A)
    any_store.append(A, entry())
    h1 = any_store.head(A)
    any_store.append(A, entry())
    h2 = any_store.head(A)
    assert h2.seq > h1.seq and h2.state_hash != h1.state_hash


def test_a_changed_entry_raises_the_alarm():
    store = MemoryLedger()
    store.ensure(A)
    seq = store.append(A, entry())
    store.tamper(A, seq, "actor_sub", "mallory")         # test hook: what someone with storage access could do
    with pytest.raises(TamperAlarm):
        store.get(A, seq)


def test_a_state_from_the_future_raises_the_alarm(tmp_path):
    """The platform keeps its last verified immudb state; a server answering from before it is an alarm."""
    import os

    from platform_service.ledger.store import ImmudbLedger
    from tests.ledger.conftest import IMMUDB_URL

    if not IMMUDB_URL:
        pytest.skip("LEDGER_TEST_IMMUDB_URL is not set (a throwaway immudb, host:port)")
    password = os.environ.get("LEDGER_TEST_IMMUDB_PASSWORD", "immudb")
    store = ImmudbLedger(IMMUDB_URL, user="immudb", password=password, state_path=tmp_path / "state")
    db = "ledger" + uuid.uuid4().hex
    store.ensure(db)
    seq = store.append(db, entry())
    state_file = next((tmp_path / "state").glob(f"{db}*"))
    state = json.loads(state_file.read_text())
    state["txId"] = int(state["txId"]) + 1_000_000            # claim a later state than the server has
    state_file.write_text(json.dumps(state))
    with pytest.raises(TamperAlarm):
        ImmudbLedger(IMMUDB_URL, user="immudb", password=password, state_path=tmp_path / "state").get(db, seq)
