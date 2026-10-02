"""A project's ledger database (spec 6.1, 7.1; second review N1, third review M1, n-c).

A project takes a free pool database of the current store's server at creation, inside the creation's
own transaction, and keeps it for ever (D2). The project's log is always found here, never derived
from its pid. With the pool empty the project is still created and its events wait (I6).
`assign` neither looks the project up nor holds a foreign key to it, so it stands alone.
"""
from __future__ import annotations

from contextlib import contextmanager

import psycopg

from platform_service import db, ledger


@contextmanager
def transaction():
    """A platform-database transaction for `assign(pid, conn=...)`: committed on success only. The
    platform's own pool, so the ledger's tables are migrated first (migration 0006)."""
    with db.pool().connection() as conn:
        with conn.transaction():
            yield conn


def _assign(conn, pid: str, server_id: str) -> str | None:
    row = conn.execute("SELECT db FROM ledger.pool WHERE assigned_pid = %s", (pid,)).fetchone()
    if row:
        return row["db"]
    row = conn.execute(
        "SELECT db FROM ledger.pool WHERE assigned_pid IS NULL AND server_id = %s"
        " ORDER BY created_at, db LIMIT 1 FOR UPDATE SKIP LOCKED", (server_id,)).fetchone()
    if not row:
        return None
    conn.execute("UPDATE ledger.pool SET assigned_pid = %s, assigned_at = clock_timestamp() WHERE db = %s",
                 (pid, row["db"]))
    return row["db"]


def assign(pid: str, conn=None) -> str | None:
    """The project's database, taken from the pool if it has none yet; None when the pool is empty or
    the store can't be reached now: the project waits (I6, review M4), it is never blocked."""
    from platform_service.ledger.store import LedgerError

    try:
        server_id = ledger.current().server_id
    except LedgerError:
        return database_for(pid)
    if conn is not None:
        with conn.transaction():                                     # a savepoint inside the caller's
            return _assign(conn, pid, server_id)
    for _ in range(3):                                               # two assigns of one pid at once
        try:
            with transaction() as own:
                return _assign(own, pid, server_id)
        except psycopg.errors.UniqueViolation:
            continue
    return database_for(pid)


def database_for(pid: str) -> str | None:
    with db.pool().connection() as conn:
        row = conn.execute("SELECT db FROM ledger.pool WHERE assigned_pid = %s", (pid,)).fetchone()
    return row["db"] if row else None


def assign_pending(pid: str) -> bool:
    """After the operator refilled the pool: give a waiting project its database."""
    return assign(pid) is not None


def assigned() -> dict[str, str]:
    """Every assignment: pid -> database (the expected-databases list, R2.10)."""
    with db.pool().connection() as conn:
        rows = conn.execute("SELECT assigned_pid::text AS pid, db FROM ledger.pool"
                            " WHERE assigned_pid IS NOT NULL").fetchall()
    return {r["pid"]: r["db"] for r in rows}


def pool_level() -> int:
    """Free databases of the current store's server."""
    with db.pool().connection() as conn:
        return conn.execute("SELECT count(*) AS n FROM ledger.pool WHERE assigned_pid IS NULL AND server_id = %s",
                            (ledger.current().server_id,)).fetchone()["n"]
