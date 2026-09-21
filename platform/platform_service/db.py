"""The platform database: a connection pool and the project queries.

Deliberately thin. There is one table, so an ORM would be more machinery than
the problem needs, and the SQL is easier to read than its abstraction.
"""
from __future__ import annotations

import os

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

_pool: ConnectionPool | None = None


def dsn() -> str:
    return os.environ.get(
        "PLATFORM_DATABASE_URL",
        "postgresql://platform_rw:platform_rw@postgres:5432/platform",
    )


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        # open=False so importing this module never touches the network; the
        # first query opens the pool, and a database that is still starting
        # produces an error on that request rather than at boot.
        _pool = ConnectionPool(dsn(), min_size=1, max_size=4, open=True, kwargs={"row_factory": dict_row})
    return _pool


def list_projects() -> list[dict]:
    with pool().connection() as conn:
        return conn.execute(
            "select pid, name, slug, description, created_at, updated_at"
            " from core.project order by created_at desc"
        ).fetchall()


def get_project(slug: str) -> dict | None:
    with pool().connection() as conn:
        return conn.execute(
            "select pid, name, slug, description, created_at, updated_at"
            " from core.project where slug = %s",
            (slug,),
        ).fetchone()


def create_project(name: str, slug: str, description: str | None) -> dict:
    with pool().connection() as conn:
        return conn.execute(
            "insert into core.project (name, slug, description) values (%s, %s, %s)"
            " returning pid, name, slug, description, created_at, updated_at",
            (name, slug, description),
        ).fetchone()
