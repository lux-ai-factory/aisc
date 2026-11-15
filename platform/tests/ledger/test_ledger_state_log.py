"""The verified ledger state is a log that only grows.

Each verified immudb state (tx id, tx hash) is a new row that follows the one it replaces, never an update
in place: the history of what the platform verified stays, two workers advancing from the same state
cannot both win, an ordinary advance never moves back, and platform_rw cannot rewrite or delete a row.
"""
from __future__ import annotations

import inspect
import uuid

import psycopg
import pytest

from platform_service.ledger.state import PostgresStateStore, State


def _name():
    return "ledger" + uuid.uuid4().hex


def _log_exists(dsn) -> bool:
    with psycopg.connect(dsn) as conn:
        return conn.execute("SELECT to_regclass('ledger.state_log') IS NOT NULL").fetchone()[0]


def test_the_verified_state_is_kept_in_a_log(platform_dsn):
    assert _log_exists(platform_dsn), "ledger.state_log does not exist"


def test_platform_rw_cannot_rewrite_or_delete_verified_state(platform_dsn):
    assert _log_exists(platform_dsn), "ledger.state_log does not exist"
    db = _name()
    PostgresStateStore(platform_dsn).put(db, State(db, 1, b"a" * 32), expected=None)
    with psycopg.connect(platform_dsn) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE ledger.state_log SET tx_id = 0 WHERE db = %s", (db,))
    with psycopg.connect(platform_dsn) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("DELETE FROM ledger.state_log WHERE db = %s", (db,))


def test_platform_rw_cannot_rewrite_the_old_state_table(platform_dsn):
    with psycopg.connect(platform_dsn) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("UPDATE ledger.state SET tx_id = tx_id WHERE false")


def test_every_advance_is_a_new_row_and_the_latest_is_read(platform_dsn):
    assert _log_exists(platform_dsn), "ledger.state_log does not exist"
    db = _name()
    store = PostgresStateStore(platform_dsn)
    first = State(db, 1, b"a" * 32)
    store.put(db, first, expected=None)
    store.put(db, State(db, 2, b"b" * 32), expected=first)
    assert store.get(db).tx_id == 2
    with psycopg.connect(platform_dsn) as conn:
        kept = [r[0] for r in conn.execute("SELECT tx_id FROM ledger.state_log WHERE db = %s ORDER BY id", (db,))]
    assert kept == [1, 2]


def test_two_advances_from_one_state_one_wins(platform_dsn):
    db = _name()
    store = PostgresStateStore(platform_dsn)
    first = State(db, 1, b"a" * 32)
    store.put(db, first, expected=None)
    store.put(db, State(db, 2, b"b" * 32), expected=first)
    with pytest.raises(ValueError, match="changed meanwhile"):
        store.put(db, State(db, 3, b"c" * 32), expected=first)


def test_an_advance_never_moves_back(platform_dsn):
    db = _name()
    store = PostgresStateStore(platform_dsn)
    first = State(db, 2, b"a" * 32)
    store.put(db, first, expected=None)
    with pytest.raises((ValueError, psycopg.Error)):
        store.put(db, State(db, 1, b"b" * 32), expected=first)
    assert store.get(db).tx_id == 2


def test_a_reanchor_is_recorded_as_such():
    assert "kind" in inspect.signature(PostgresStateStore.put).parameters, \
        "PostgresStateStore.put takes no kind: a reanchor cannot be told from an advance"
