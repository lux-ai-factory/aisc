"""The platform database: a connection pool and the project queries.

Deliberately thin. There is one table, so an ORM would be more machinery than
the problem needs, and the SQL is easier to read than its abstraction.
"""
from __future__ import annotations

import os

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

from platform_service.migrate import migrate
from platform_service.projects import looks_like_pid

_pool: ConnectionPool | None = None


def dsn() -> str:
    return os.environ.get(
        "PLATFORM_DATABASE_URL",
        "postgresql://platform_rw:platform_rw@postgres:5432/platform",
    )


def bootstrap_subjects() -> list[str]:
    """Who owns the projects that predate membership.

    Named in the environment because the platform does not have a user
    directory of its own: Keycloak does, and these are its subjects.
    """
    raw = os.environ.get("PLATFORM_BOOTSTRAP_OWNERS", "")
    return [s.strip() for s in raw.split(",") if s.strip()]


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        # open=False so importing this module never touches the network; the
        # first query opens the pool, and a database that is still starting
        # produces an error on that request rather than at boot.
        _pool = ConnectionPool(dsn(), min_size=1, max_size=4, open=True, kwargs={"row_factory": dict_row})
        # core is this service's to migrate, and it is migrated before it is
        # read. Here rather than at import, so importing the module still
        # touches nothing, and here rather than in a startup event, because a
        # test client that never starts the app would then run on a schema that
        # does not match the code.
        with _pool.connection() as conn:
            migrate(conn)
        bootstrap_owners(bootstrap_subjects())
        provision_all()
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


def create_project(name: str, slug: str, description: str | None,
                   owner: str, email: str | None = None) -> dict:
    """A new project, owned by whoever made it.

    One transaction: a project with no members would be one nobody can open,
    and it is not worth being able to create that state even briefly.
    """
    with pool().connection() as conn, conn.transaction():
        created = conn.execute(
            "insert into core.project (name, slug, description) values (%s, %s, %s)"
            " returning pid, name, slug, description, created_at, updated_at",
            (name, slug, description),
        ).fetchone()
        conn.execute(
            "insert into core.project_member (project_id, subject, email, role)"
            " values (%s, %s, %s, 'owner')",
            (created["pid"], owner, email),
        )
        return created


def delete_project(pid) -> None:
    with pool().connection() as conn:
        conn.execute("delete from core.project where pid = %s", (pid,))


def provision_all() -> None:
    """Every project has its database: the ones made before there were any get
    theirs here, at the first query after start."""
    from platform_service import projectdb

    with pool().connection() as conn:
        pids = [r["pid"] for r in conn.execute("select pid from core.project").fetchall()]
    for pid in pids:
        projectdb.provision(dsn(), pid)


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


# ── membership ───────────────────────────────────────────────────────────────
# A project belongs to the people in it. Every query that returns a project, or
# anything inside one, passes through here: filtering in one place is what makes
# it hard to add an endpoint that forgets.


def _project_pid(conn, identifier: str) -> str | None:
    column = "pid" if looks_like_pid(identifier) else "slug"
    found = conn.execute(
        f"select pid from core.project where {column} = %s", (identifier,)
    ).fetchone()
    return found["pid"] if found else None


def role_in_project(project: str, subject: str) -> str | None:
    """What this person is to this project, or None if they are not in it."""
    with pool().connection() as conn:
        column = "pid" if looks_like_pid(project) else "slug"
        found = conn.execute(
            "select m.role from core.project_member m"
            "  join core.project p on p.pid = m.project_id"
            f" where p.{column} = %s and m.subject = %s",
            (project, subject),
        ).fetchone()
        return found["role"] if found else None


def projects_for(subject: str) -> list[dict]:
    with pool().connection() as conn:
        return conn.execute(
            "select p.pid, p.name, p.slug, p.description, p.created_at, p.updated_at,"
            "       m.role"
            "  from core.project p join core.project_member m on m.project_id = p.pid"
            " where m.subject = %s order by p.created_at desc",
            (subject,),
        ).fetchall()


def members(project: str) -> list[dict]:
    with pool().connection() as conn:
        column = "pid" if looks_like_pid(project) else "slug"
        return conn.execute(
            "select m.subject, m.email, m.role, m.added_at"
            "  from core.project_member m join core.project p on p.pid = m.project_id"
            f" where p.{column} = %s order by m.added_at",
            (project,),
        ).fetchall()


def add_member(project: str, subject: str, email: str | None, role: str) -> dict | None:
    """Put somebody in a project, or change what they are in it."""
    with pool().connection() as conn:
        pid = _project_pid(conn, project)
        if pid is None:
            return None
        return conn.execute(
            "insert into core.project_member (project_id, subject, email, role)"
            " values (%s, %s, %s, %s)"
            " on conflict (project_id, subject) do update"
            "    set role = excluded.role,"
            "        email = coalesce(excluded.email, core.project_member.email)"
            " returning subject, email, role, added_at",
            (pid, subject, email, role),
        ).fetchone()


def owner_count(project: str) -> int:
    with pool().connection() as conn:
        column = "pid" if looks_like_pid(project) else "slug"
        found = conn.execute(
            "select count(*) as n from core.project_member m"
            "  join core.project p on p.pid = m.project_id"
            f" where p.{column} = %s and m.role = 'owner'",
            (project,),
        ).fetchone()
        return found["n"]


def remove_member(project: str, subject: str) -> bool:
    with pool().connection() as conn:
        pid = _project_pid(conn, project)
        if pid is None:
            return False
        done = conn.execute(
            "delete from core.project_member where project_id = %s and subject = %s",
            (pid, subject),
        )
        return done.rowcount > 0


def bootstrap_owners(subjects: list[str]) -> int:
    """Make these people owners of every project that has nobody in it.

    The projects that existed before membership did have no members, and a
    project nobody is in is a project nobody can open. Only those: a project
    that has members is already answered for, so running this again changes
    nothing.
    """
    if not subjects:
        return 0
    with pool().connection() as conn:
        return conn.execute(
            "insert into core.project_member (project_id, subject, role)"
            " select p.pid, s.subject, 'owner'"
            "   from core.project p cross join unnest(%s::text[]) as s(subject)"
            "  where not exists (select 1 from core.project_member m where m.project_id = p.pid)"
            " on conflict do nothing",
            (subjects,),
        ).rowcount
