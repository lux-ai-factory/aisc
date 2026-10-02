"""Who is behind an actor reference (spec 6.1, 7.5; I10, S8).

The ledger, the witness records and every index hold only `actor_ref`, a random `actor:` + 32 hex, one
per (scope, person); the scope is the project's pid, or `platform` for requests outside any project.
This module keeps the mapping, in its own database `ledger_identity` (made by
init/project-databases.sql, owned by platform_rw, CONNECT for nobody else), so pgAdmin's read-all role
can't see it.

- `ref_for` makes a reference on first sight (unique on scope and subject, so two first sightings at
  once make one) and keeps the name current.
- `resolve` checks the row's MAC (reference, subject and name) and raises `MappingAlarm` on an edited
  row.
- `erase` deletes the rows: references are random, so the link is then gone for good.
"""
from __future__ import annotations

import os
import secrets as _random
import threading

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from platform_service.ledger import secrets
from platform_service.ledger.canonical import canonical

DATABASE = "ledger_identity"
MIGRATIONS = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                          "ledger-identity")
_migrated: set[str] = set()
_lock = threading.Lock()


class MappingAlarm(Exception):
    """A mapping row doesn't match its MAC: someone edited who is behind a reference."""


def _dsn() -> str:
    return make_conninfo(os.environ["PLATFORM_DATABASE_URL"], dbname=DATABASE)


def _connect():
    """A connection to ledger_identity, its table migrated on first use (platform_rw owns it)."""
    dsn = _dsn()
    conn = psycopg.connect(dsn, row_factory=dict_row)
    if dsn not in _migrated:
        from pathlib import Path

        from platform_service.migrate import migrate

        with _lock:
            if dsn not in _migrated:
                migrate(conn, Path(MIGRATIONS), "identity.schema_migration")
                _migrated.add(dsn)
    return conn


def _scope(pid) -> str:
    return "platform" if pid is None else str(pid).lower()


def _mac(pid, actor_ref: str, sub: str, name: str) -> str:
    return secrets.digest(pid, "mapping", canonical([actor_ref, sub, name]))


def ref_for(pid, sub: str, name: str) -> str:
    """The person's reference in this scope, made on first sight; the name is kept current."""
    scope = _scope(pid)
    with _connect() as conn:
        for _ in range(3):
            row = conn.execute("SELECT actor_ref, name FROM identity.actor WHERE scope = %s AND sub = %s",
                               (scope, sub)).fetchone()
            if row:
                if row["name"] != name:
                    conn.execute("UPDATE identity.actor SET name = %s, mac = %s, updated_at = clock_timestamp()"
                                 " WHERE actor_ref = %s", (name, _mac(pid, row["actor_ref"], sub, name), row["actor_ref"]))
                return row["actor_ref"]
            ref = "actor:" + _random.token_hex(16)
            made = conn.execute("INSERT INTO identity.actor (scope, actor_ref, sub, name, mac) VALUES (%s, %s, %s, %s, %s)"
                                " ON CONFLICT (scope, sub) DO NOTHING", (scope, ref, sub, name, _mac(pid, ref, sub, name)))
            if made.rowcount == 1:
                return ref
        raise RuntimeError("could not make an actor reference")


def resolve(pid, actor_ref) -> tuple[str, str] | None:
    """(sub, name) behind a reference, or None once erased; MappingAlarm if the row was edited."""
    if not actor_ref:
        return None
    with _connect() as conn:
        row = conn.execute("SELECT sub, name, mac FROM identity.actor WHERE scope = %s AND actor_ref = %s",
                           (_scope(pid), actor_ref)).fetchone()
    if row is None:
        return None
    if not secrets.check(pid, "mapping", canonical([actor_ref, row["sub"], row["name"]]), row["mac"]):
        raise MappingAlarm(f"the mapping of {actor_ref} was changed outside the platform")
    return row["sub"], row["name"]


def erase(pid, sub: str) -> int:
    """Delete a person's mapping in this scope; their entries stay, now unlinkable (I10)."""
    with _connect() as conn:
        return conn.execute("DELETE FROM identity.actor WHERE scope = %s AND sub = %s", (_scope(pid), sub)).rowcount


def tamper(pid, actor_ref: str, *, sub: str | None = None, name: str | None = None) -> None:
    """Test hook: edit a mapping row the way someone with database rights could, without its MAC."""
    with _connect() as conn:
        if sub is not None:
            conn.execute("UPDATE identity.actor SET sub = %s WHERE actor_ref = %s", (sub, actor_ref))
        if name is not None:
            conn.execute("UPDATE identity.actor SET name = %s WHERE actor_ref = %s", (name, actor_ref))
