"""The verified state of each ledger database, kept outside immudb (spec 6.1; spike M11, M13-M15).

A state is immudb's (tx id, tx hash) the platform last verified. It only moves forward: `put` is a
compare-and-set, so two workers can't move it back, and a server answering from before it is a
rollback (TamperAlarm in the store). Keyed by database name only, never by server address (M11).
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class State:
    db: str
    tx_id: int
    tx_hash: bytes
    signature: bytes | None = None

    def claiming(self, *, tx_id: int) -> "State":
        """Test hook: a state that claims another tx id than the one verified."""
        return replace(self, tx_id=tx_id)


class MemoryStateStore:
    """In memory, for tests."""

    def __init__(self):
        self._states: dict[str, State] = {}
        self._lock = threading.Lock()

    def get(self, db: str) -> State | None:
        with self._lock:
            return self._states.get(db)

    def put(self, db: str, state: State, *, expected: State | None) -> None:
        with self._lock:
            if self._states.get(db) != expected:
                raise ValueError(f"the verified state of {db} changed meanwhile")
            self._states[db] = state


class PostgresStateStore:
    """`ledger.state` in the platform database (migration 0006)."""

    def __init__(self, dsn: str | None = None):
        self._dsn = dsn

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        if self._dsn:
            return psycopg.connect(self._dsn, row_factory=dict_row)
        from platform_service import db

        return db.pool().connection()

    def get(self, db: str) -> State | None:
        with self._connect() as conn:
            row = conn.execute("SELECT tx_id, tx_hash, signature FROM ledger.state WHERE db = %s", (db,)).fetchone()
        if not row:
            return None
        return State(db, row["tx_id"], bytes(row["tx_hash"]),
                     bytes(row["signature"]) if row["signature"] is not None else None)

    def put(self, db: str, state: State, *, expected: State | None) -> None:
        with self._connect() as conn:
            if expected is None:
                done = conn.execute(
                    "INSERT INTO ledger.state (db, tx_id, tx_hash, signature) VALUES (%s, %s, %s, %s)"
                    " ON CONFLICT (db) DO NOTHING", (db, state.tx_id, state.tx_hash, state.signature)).rowcount
            else:
                done = conn.execute(
                    "UPDATE ledger.state SET tx_id = %s, tx_hash = %s, signature = %s, updated_at = clock_timestamp()"
                    " WHERE db = %s AND tx_id = %s AND tx_hash = %s",
                    (state.tx_id, state.tx_hash, state.signature, db, expected.tx_id, expected.tx_hash)).rowcount
            if done != 1:
                raise ValueError(f"the verified state of {db} changed meanwhile")
