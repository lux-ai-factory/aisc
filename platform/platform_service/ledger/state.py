"""The verified state of each ledger database, kept outside immudb.

A state is immudb's (tx id, tx hash) the platform last verified. It only moves forward: `put` is a
compare-and-set, so two workers can't move it back, and a server answering from before it is a
rollback (TamperAlarm in the store). Keyed by database name only, never by server address.

In Postgres every state is a new row of a log that only grows (`ledger.state_log`): the latest row is the
state, and a `kind` says whether it is an ordinary advance or a reanchor after a restore (which may move
back, because an admin checked the server's new head).
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

    def put(self, db: str, state: State, *, expected: State | None, kind: str = "advance") -> None:
        with self._lock:
            if self._states.get(db) != expected:
                raise ValueError(f"the verified state of {db} changed meanwhile")
            self._states[db] = state


class PostgresStateStore:
    """`ledger.state_log` in the platform database (migration 0016): one row per verified state, each
    following the one it replaces. platform_rw may only insert and read it."""

    def __init__(self, dsn: str | None = None):
        self._dsn = dsn

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row

        if self._dsn:
            return psycopg.connect(self._dsn, row_factory=dict_row)
        from platform_service import db

        return db.pool().connection()

    @staticmethod
    def _latest(conn, db: str):
        return conn.execute("SELECT id, tx_id, tx_hash, signature FROM ledger.state_log WHERE db = %s"
                            " ORDER BY id DESC LIMIT 1", (db,)).fetchone()

    @staticmethod
    def _state(db: str, row) -> State:
        return State(db, row["tx_id"], bytes(row["tx_hash"]),
                     bytes(row["signature"]) if row["signature"] is not None else None)

    def get(self, db: str) -> State | None:
        with self._connect() as conn:
            row = self._latest(conn, db)
        return self._state(db, row) if row else None

    def put(self, db: str, state: State, *, expected: State | None, kind: str = "advance") -> None:
        """Record `state` as following `expected`, the latest state (None: the first). Raises ValueError when the
        latest is another one, or another worker recorded one after it meanwhile. An advance that moves back is
        refused by the database; a reanchor (`kind="reanchor"`) may."""
        import psycopg

        if kind not in ("advance", "reanchor"):
            raise ValueError(f"not a kind of state: {kind!r}")
        changed = ValueError(f"the verified state of {db} changed meanwhile")
        with self._connect() as conn:
            latest = self._latest(conn, db)
            if (None if latest is None else self._state(db, latest)) != expected:
                raise changed
            try:
                conn.execute(
                    "INSERT INTO ledger.state_log (db, follows, tx_id, tx_hash, signature, kind)"
                    " VALUES (%s, %s, %s, %s, %s, %s)",
                    (db, None if latest is None else latest["id"], state.tx_id, state.tx_hash, state.signature, kind))
            except psycopg.errors.UniqueViolation:
                raise changed from None
