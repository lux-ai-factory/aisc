"""The lock that guards a project's card state (card version, revision).

The card state moves when qualification stores a card. A writer that reads "the latest card" to stamp a
record, or to compare it with what a page sent, must not read it while a card is being stored, and no card
may be stored between that read and the writer's commit. Both sides take one advisory lock in the project's
database, on the key the platform's version counter already takes:

- the writer that stores a card (and the platform's create, revise and withdraw) takes it exclusive;
- every stamping writer takes it shared, in its own transaction, before it reads the latest card.

Both are transaction locks: they end with the transaction and need no release. Taken in autocommit they
would end at once and guard nothing, so both refuse to run outside a transaction.

This module and its TypeScript twin (shared/access-ts/cardLock.ts) are the only places that spell the key.
`conn` is a psycopg connection (psycopg2's works too); a caller on SQLAlchemy or Django passes the driver's
connection under it.
"""
from __future__ import annotations

#: the lock's key, as SQL
KEY_SQL = "hashtext('project.system')"

_EXCLUSIVE = f"SELECT pg_advisory_xact_lock({KEY_SQL})"
_SHARED = f"SELECT pg_advisory_xact_lock_shared({KEY_SQL})"


#: libpq's "idle": connected, no transaction open (psycopg's TransactionStatus.IDLE, psycopg2's
#: TRANSACTION_STATUS_IDLE)
_IDLE = 0


class NotInTransaction(RuntimeError):
    """The card lock was asked for outside a transaction, where it would be released at once."""


def exclusive(conn) -> None:
    """Take the card lock exclusive: for the transaction that stores a card or moves the version counter."""
    _take(conn, _EXCLUSIVE)


def shared(conn) -> None:
    """Take the card lock shared: for a transaction that reads the latest card to stamp or compare it."""
    _take(conn, _SHARED)


def _take(conn, sql: str) -> None:
    # Without autocommit psycopg opens a transaction with the first statement, this one included; with it,
    # only an open transaction block keeps the lock.
    if conn.autocommit and conn.info.transaction_status == _IDLE:
        raise NotInTransaction("the card lock is a transaction lock: take it inside a transaction")
    with conn.cursor() as cursor:
        cursor.execute(sql)
