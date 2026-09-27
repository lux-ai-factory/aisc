"""The connection pool, and the migrations it applies before it hands out a connection."""
from __future__ import annotations

import pathlib

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from aisc_connectors.settings import settings

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"
#: Two services starting at once must not both apply 0001.
_LOCK = 0x636F6E6E
_pool: ConnectionPool | None = None


def migrate(dsn: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(dsn) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS connector.schema_migration"
            " (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        done = {r[0] for r in conn.execute("SELECT name FROM connector.schema_migration")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            conn.execute(path.read_text())
            conn.execute("INSERT INTO connector.schema_migration (name) VALUES (%s)", (path.name,))
            applied.append(path.name)
        conn.commit()
    return applied


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        dsn = settings().database_url
        migrate(dsn)
        _pool = ConnectionPool(dsn, kwargs={"row_factory": dict_row}, open=True)
    return _pool


def reset_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
    _pool = None
