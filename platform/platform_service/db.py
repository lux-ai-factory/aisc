"""The platform database: a connection pool and the project queries.

Deliberately thin. There is one table, so an ORM would be more machinery than
the problem needs, and the SQL is easier to read than its abstraction.
"""
from __future__ import annotations

import os

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

from platform_service.projects import looks_like_pid

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


def get_project(identifier: str) -> dict | None:
    """The project named by a slug or by its pid: a page has one or the other,
    and both name the same project."""
    column = "pid" if looks_like_pid(identifier) else "slug"
    with pool().connection() as conn:
        return conn.execute(
            "select pid, name, slug, description, created_at, updated_at"
            f" from core.project where {column} = %s",
            (identifier,),
        ).fetchone()


def create_project(name: str, slug: str, description: str | None) -> dict:
    with pool().connection() as conn:
        return conn.execute(
            "insert into core.project (name, slug, description) values (%s, %s, %s)"
            " returning pid, name, slug, description, created_at, updated_at",
            (name, slug, description),
        ).fetchone()


# ── systems ──────────────────────────────────────────────────────────────────
# The system under assessment, inside a project. Written only here: every
# module reads `core`, and one writer is what keeps the name meaning one thing.


def list_systems(project: str) -> list[dict]:
    column = "pid" if looks_like_pid(project) else "slug"
    with pool().connection() as conn:
        return conn.execute(
            "select s.pid, s.project_id, s.name, s.version, s.provider, s.description,"
            "       s.created_at, s.updated_at"
            "  from core.system s join core.project p on p.pid = s.project_id"
            f" where p.{column} = %s order by s.name, s.version",
            (project,),
        ).fetchall()


def get_system(pid: str) -> dict | None:
    with pool().connection() as conn:
        return conn.execute(
            "select pid, project_id, name, version, provider, description,"
            "       created_at, updated_at from core.system where pid = %s",
            (pid,),
        ).fetchone()


def register_system(
    project: str, name: str, version: str | None, provider: str | None,
    description: str | None,
) -> dict | None:
    """The system with this name and version in this project, making it if it
    is new. Registering the same system twice is the same system, not a second
    one, so a module may call this every time it starts work. Returns None when
    there is no such project."""
    with pool().connection() as conn:
        column = "pid" if looks_like_pid(project) else "slug"
        found = conn.execute(
            f"select pid from core.project where {column} = %s", (project,)
        ).fetchone()
        if found is None:
            return None
        return conn.execute(
            "insert into core.system (project_id, name, version, provider, description)"
            " values (%s, %s, %s, %s, %s)"
            " on conflict (project_id, name, (coalesce(version, ''))) do update"
            "    set provider = coalesce(excluded.provider, core.system.provider),"
            "        description = coalesce(excluded.description, core.system.description),"
            "        updated_at = now()"
            " returning pid, project_id, name, version, provider, description,"
            "           created_at, updated_at",
            (found["pid"], name, version, provider, description),
        ).fetchone()
