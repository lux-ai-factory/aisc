"""The platform database: a connection pool and the project queries.

Deliberately thin. There is one table, so an ORM would be more machinery than
the problem needs, and the SQL is easier to read than its abstraction.
"""
from __future__ import annotations

import logging
import os
import threading
import time

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row

from platform_service.migrate import migrate
from platform_service.projects import looks_like_pid

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None
#: Setup, done once per process, and only marked done once it has worked: a
#: database still starting, or one project that cannot be provisioned, is
#: tried again at a later pool() call instead of never.
_migrated = False
#: The projects whose database still has to be made or brought up to date.
#: None until the projects have been listed.
_unprovisioned: set[str] | None = None
_last_attempt = 0.0
#: How long a project that failed to provision is left before it is tried
#: again, so a broken one costs a connection attempt a minute, not one a request.
RETRY_SECONDS = 60.0
_setup_lock = threading.RLock()
_in_setup = False


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
    global _pool, _in_setup
    with _setup_lock:
        if _pool is None:
            # Made at the first query, so importing this module never touches
            # the network, and a database that is still starting produces an
            # error on that request rather than at boot.
            _pool = ConnectionPool(dsn(), min_size=1, max_size=4, open=True, kwargs={"row_factory": dict_row})
        # The setup below queries through pool() itself; while it runs, this
        # thread (the lock is reentrant) gets the pool as it is.
        if not _in_setup and _setup_pending():
            _in_setup = True
            try:
                _setup(_pool)
            finally:
                _in_setup = False
    return _pool


def _setup_pending() -> bool:
    if not _migrated or _unprovisioned is None:
        return True
    return bool(_unprovisioned) and time.monotonic() - _last_attempt >= RETRY_SECONDS


def reset() -> None:
    """Forget the pool and the setup, as a fresh process would. For tests."""
    global _pool, _migrated, _unprovisioned, _last_attempt
    with _setup_lock:
        if _pool is not None:
            _pool.close()
        _pool, _migrated, _unprovisioned, _last_attempt = None, False, None, 0.0


def _setup(p: ConnectionPool) -> None:
    """core is this service's to migrate, and it is migrated before it is read.
    Here rather than at import, so importing the module still touches nothing,
    and here rather than in a startup event, because a test client that never
    starts the app would then run on a schema that does not match the code.

    A failure here raises to the request that caused it and leaves the step
    not done, so the next pool() call does it again."""
    global _migrated
    if not _migrated:
        with p.connection() as conn:
            migrate(conn)
        bootstrap_owners(bootstrap_subjects())
        _migrated = True
    provision_all()


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
        # born with its one AI system, version 1 as a draft named after it
        system = conn.execute(
            "insert into core.ai_system (project_id) values (%s) returning pid",
            (created["pid"],),
        ).fetchone()
        conn.execute(
            "insert into core.ai_system_version (ai_system_id, number, name, created_by)"
            " values (%s, 1, %s, %s)",
            (system["pid"], name, owner),
        )
        return created


def delete_project(pid) -> None:
    with pool().connection() as conn:
        conn.execute("delete from core.project where pid = %s", (pid,))


def provision_all() -> list[str]:
    """Every project has its database: the ones made before there were any get
    theirs here, at the first query after start.

    Each project on its own: one that cannot be provisioned is logged and left
    for the next attempt, and does not keep the others from theirs. Returns the
    pids still without one."""
    from platform_service import projectdb

    global _unprovisioned, _last_attempt
    with pool().connection() as conn:
        current = {str(r["pid"]) for r in conn.execute("select pid from core.project").fetchall()}
    # The first time, every project; after that, the ones that failed and still
    # exist (retrying one deleted meanwhile would make it a database again).
    _unprovisioned = current if _unprovisioned is None else _unprovisioned & current
    _last_attempt = time.monotonic()
    for pid in sorted(_unprovisioned):
        try:
            projectdb.provision(dsn(), pid)
        except Exception:
            logger.exception("could not provision the database of project %s; trying again later", pid)
            continue
        _unprovisioned.discard(pid)
    return sorted(_unprovisioned)


# ── systems ──────────────────────────────────────────────────────────────────
# The system under assessment, inside a project. Written only here: every
# module reads `core`, and one writer is what keeps the name meaning one thing.


_VERSION = (
    "v.pid, v.ai_system_id, v.number, v.name, v.release, v.provider, v.description,"
    " v.created_at, v.created_by, v.frozen_at, v.frozen_reason"
)


def ai_system(project: str) -> dict | None:
    """The project's one AI system with its versions, newest first. None when
    there is no such project."""
    column = "pid" if looks_like_pid(project) else "slug"
    with pool().connection() as conn:
        found = conn.execute(
            "select a.pid, a.project_id, a.created_at from core.ai_system a"
            f" join core.project p on p.pid = a.project_id where p.{column} = %s",
            (project,),
        ).fetchone()
        if found is None:
            return None
        versions = conn.execute(
            f"select {_VERSION} from core.ai_system_version v"
            " where v.ai_system_id = %s order by v.number desc",
            (found["pid"],),
        ).fetchall()
    return {**found, "current": versions[0] if versions else None, "versions": versions}


def get_ai_system_version(pid: str) -> dict | None:
    """A version by its own id, with the project it belongs to."""
    with pool().connection() as conn:
        return conn.execute(
            f"select {_VERSION}, a.project_id from core.ai_system_version v"
            " join core.ai_system a on a.pid = v.ai_system_id where v.pid = %s",
            (pid,),
        ).fetchone()


def edit_ai_system(project: str, changes: dict, needs_draft: bool = False,
                   subject: str | None = None) -> dict | None:
    """Apply an edit to the project's AI system, as ai_system.plan_edit says.

    Returns {"version": the version the edit landed in, "forked_from": the pid
    it was copied from, or None}. The system row is locked for the length of
    the edit, so two editors at once make one next version, not two.
    """
    from platform_service.ai_system import plan_edit

    column = "pid" if looks_like_pid(project) else "slug"
    with pool().connection() as conn, conn.transaction():
        system = conn.execute(
            "select a.pid from core.ai_system a join core.project p on p.pid = a.project_id"
            f" where p.{column} = %s for update of a",
            (project,),
        ).fetchone()
        if system is None:
            return None
        latest = conn.execute(
            f"select {_VERSION} from core.ai_system_version v where v.ai_system_id = %s"
            " order by v.number desc limit 1",
            (system["pid"],),
        ).fetchone()
        plan = plan_edit(latest, changes, needs_draft=needs_draft)
        forked_from = None
        if plan["action"] == "update":
            sets = ", ".join(f"{field} = %s" for field in plan["fields"])
            conn.execute(
                f"update core.ai_system_version set {sets} where pid = %s",
                (*plan["fields"].values(), plan["pid"]),
            )
            pid = plan["pid"]
        elif plan["action"] == "fork":
            fields = plan["fields"]
            pid = conn.execute(
                "insert into core.ai_system_version"
                " (ai_system_id, number, name, release, provider, description, created_by)"
                " values (%s, %s, %s, %s, %s, %s, %s) returning pid",
                (system["pid"], plan["number"], fields["name"], fields["release"],
                 fields["provider"], fields["description"], subject),
            ).fetchone()["pid"]
            forked_from = plan["from_pid"]
        else:
            pid = plan["pid"]
        version = conn.execute(
            f"select {_VERSION} from core.ai_system_version v where v.pid = %s", (pid,)
        ).fetchone()
    return {"version": version, "forked_from": forked_from}


def freeze_ai_system_version(pid: str, reason: str) -> dict | None:
    """Freeze a version because something now depends on it. Freezing a frozen
    version changes nothing: the first reason and moment are the ones kept."""
    with pool().connection() as conn:
        conn.execute(
            "update core.ai_system_version set frozen_at = now(), frozen_reason = %s"
            " where pid = %s and frozen_at is null",
            (reason, pid),
        )
    return get_ai_system_version(pid)


def _as_old_system(version: dict, project_id) -> dict:
    """A version in the shape core.system had, for callers not yet moved."""
    return {"pid": version["pid"], "project_id": project_id, "name": version["name"],
            "version": version["release"], "provider": version["provider"],
            "description": version["description"], "created_at": version["created_at"],
            "updated_at": version["created_at"]}


def list_systems(project: str) -> list[dict]:
    """The one system, as the list core.system used to answer with."""
    found = ai_system(project)
    if found is None or found["current"] is None:
        return []
    return [_as_old_system(found["current"], found["project_id"])]


def get_system(pid: str) -> dict | None:
    found = get_ai_system_version(pid)
    return None if found is None else _as_old_system(found, found["project_id"])


def register_system(
    project: str, name: str, version: str | None, provider: str | None,
    description: str | None,
) -> dict | None:
    """What naming a system meant before there was one per project: now it is
    an edit of that one system, and answers with the version it landed in."""
    changes = {"name": name, "release": version}
    if provider is not None:
        changes["provider"] = provider
    if description is not None:
        changes["description"] = description
    edited = edit_ai_system(project, changes)
    if edited is None:
        return None
    found = ai_system(project)
    return _as_old_system(edited["version"], found["project_id"])


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
