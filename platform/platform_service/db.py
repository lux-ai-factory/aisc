"""The platform database: a connection pool and the queries on `core`.

Deliberately thin. A handful of tables (projects and their members here; the
AI card versions in each project's own database), so an ORM would be more
machinery than the problem needs, and the SQL is easier to read than its
abstraction.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import psycopg
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

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
#: Projects the dashboard bridge has not taken yet: retried by provision_all.
_unregistered: set[str] = set()
#: Whether provision_all has registered every project since the start.
_registered_all = False
_setup_lock = threading.RLock()
_in_setup = False


_PROJECT = "pid, name, slug, description, created_at, updated_at"


def _key_column(identifier: str) -> str:
    """A project is named by its pid or by its slug; which column that is."""
    return "pid" if looks_like_pid(identifier) else "slug"


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
    return bool(_unprovisioned or _unregistered) and time.monotonic() - _last_attempt >= RETRY_SECONDS


def remember_unregistered(pid) -> None:
    """The dashboard bridge did not take this project: provision_all tries again."""
    with _setup_lock:
        _unregistered.add(str(pid))


def reset() -> None:
    """Forget the pool and the setup, as a fresh process would. For tests."""
    global _pool, _migrated, _unprovisioned, _last_attempt, _registered_all
    with _setup_lock:
        if _pool is not None:
            _pool.close()
        _pool, _migrated, _unprovisioned, _last_attempt = None, False, None, 0.0
        _unregistered.clear()
        _registered_all = False


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
        return conn.execute(f"select {_PROJECT} from core.project order by created_at desc").fetchall()


def get_project(identifier: str) -> dict | None:
    """The project named by a slug or by its pid: a page has one or the other,
    and both name the same project."""
    with pool().connection() as conn:
        return conn.execute(
            f"select {_PROJECT} from core.project where {_key_column(identifier)} = %s",
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
            f" returning {_PROJECT}",
            (name, slug, description),
        ).fetchone()
        conn.execute(
            "insert into core.project_member (project_id, subject, email, role)"
            " values (%s, %s, %s, 'owner')",
            (created["pid"], owner, email),
        )
        # the project's ledger database, from the operator's pool, in the same transaction (spec 7.1)
        from platform_service.ledger import outbox, provision

        provision.assign(str(created["pid"]), conn=conn)
        # recorded in the platform log: the request that made it named no project yet (spec 4.2)
        outbox.emit(conn, "project.created", project_pid=None, item_type="project", item_id=created["pid"],
                    details={"name": name})
        return created


def delete_project(pid) -> None:
    from platform_service.ledger import outbox

    with pool().connection() as conn, conn.transaction():
        members = conn.execute("select count(*) as n from core.project_member where project_id = %s",
                               (pid,)).fetchone()
        outbox.emit(conn, "project.deleted", project_pid=pid, item_type="project", item_id=pid,
                    details={"members": members["n"] if members else 0})
        conn.execute("delete from core.project where pid = %s", (pid,))


def provision_all() -> list[str]:
    """Every project has its database: the ones made before there were any get
    theirs here, at the first query after start.

    Each project on its own: one that cannot be provisioned is logged and left
    for the next attempt, and does not keep the others from theirs. Returns the
    pids still without one."""
    global _registered_all
    with pool().connection() as conn:
        rows = conn.execute("select pid, slug, name from core.project").fetchall()
    known = {str(r["pid"]): r for r in rows}
    _provision_pending(set(known))
    _register_pending(known)
    _registered_all = True
    return sorted(_unprovisioned)


def _provision_pending(current: set[str]) -> None:
    """The first time, every project; after that, the ones that failed and still
    exist (retrying one deleted meanwhile would make it a database again)."""
    from platform_service import projectdb

    global _unprovisioned, _last_attempt
    _unprovisioned = set(current) if _unprovisioned is None else _unprovisioned & current
    _last_attempt = time.monotonic()
    for pid in sorted(_unprovisioned):
        try:
            projectdb.provision(dsn(), pid)
        except Exception:
            logger.exception("could not provision the database of project %s; trying again later", pid)
            continue
        _unprovisioned.discard(pid)


def _register_pending(known: dict[str, dict]) -> None:
    """The dashboard gets every project with a database on the first run after a
    start; after that, the ones whose registration failed and that still exist."""
    from platform_service import dashboard_bridge

    ready = set(known) - _unprovisioned
    todo = ready if not _registered_all else (_unregistered & ready)
    _unregistered.intersection_update(known)
    for pid in sorted(todo):
        row = known[pid]
        if dashboard_bridge.register(pid, row["slug"], row["name"]):
            _unregistered.discard(pid)
        else:
            _unregistered.add(pid)


# ── card versions ────────────────────────────────────────────────────────────
# The saved versions of a project's AI card, one row each in project.system of
# that project's own database (isolation 2026-09-25, 01-specs.md I1.5, I2.2, D1,
# D2). Written only here, as platform_rw, the owner of every project database:
# one writer keeps the numbering in one place. The shared table they used to be
# rows of is never read or written again. Every call opens that database, uses
# it and closes it (I17.1), like llm_store: nothing pooled is left on a
# database that may be dropped.


class ProjectDatabaseGone(LookupError):
    """The project's row exists, its database does not (between drop and delete)."""


#: The order of a version in every response (unchanged by the isolation).
_VERSION_COLUMNS = "pid, project_id, number, name, version, provider, description, created_at, created_by"
#: What project.system has of those: every column but project_id (the database is the project).
_STORED = "pid, number, name, version, provider, description, created_at, created_by"


def _is_missing_database(exc: Exception) -> bool:
    return "does not exist" in str(exc) and "database" in str(exc)


def project_connection(pid) -> psycopg.Connection:
    """A new connection to this project's database, as the platform's own role.

    Raises ProjectDatabaseGone when the database is not there: looked up first,
    and also when it is dropped between that look and the connect."""
    from platform_service import projectdb

    name = projectdb.database_name(pid)
    with pool().connection() as conn:
        exists = conn.execute("select 1 from pg_database where datname = %s", (name,)).fetchone()
    if exists is None:
        raise ProjectDatabaseGone(str(pid))
    try:
        return psycopg.connect(make_conninfo(dsn(), dbname=name), row_factory=dict_row)
    except psycopg.OperationalError as exc:
        if _is_missing_database(exc):
            raise ProjectDatabaseGone(str(pid)) from None
        raise


def _project_ref(conn, identifier: str) -> dict | None:
    """{"pid", "slug"} of the project named by its pid or slug, from core.project."""
    return conn.execute(
        f"select pid, slug from core.project where {_key_column(identifier)} = %s", (identifier,)
    ).fetchone()


def _as_version(row: dict | None, project_pid) -> dict | None:
    """A project.system row in the response shape of before: project_id is the project's pid."""
    if row is None:
        return None
    out = {"pid": row["pid"], "project_id": project_pid}
    out.update({c: row[c] for c in _VERSION_COLUMNS.split(", ")[2:]})
    if "updated_at" in row:
        out["updated_at"] = row["updated_at"]
    return out


def _resolve(project: str):
    with pool().connection() as conn:
        found = _project_ref(conn, project)
    return found["pid"] if found else None


def create_version(project: str, name: str, version: str | None, provider: str | None,
                   description: str | None, subject: str | None) -> dict | None:
    """The project's next card version, numbered max+1 under an advisory lock
    taken in the project's database, so two saves at once get n and n+1.
    None: no such project. ProjectDatabaseGone: its database is gone."""
    pid = _resolve(project)
    if pid is None:
        return None
    with project_connection(pid) as conn, conn.transaction():
        conn.execute("select pg_advisory_xact_lock(hashtext('project.system'))")
        row = conn.execute(
            "insert into project.system (number, name, version, provider, description, created_by)"
            " values ((select coalesce(max(number), 0) + 1 from project.system), %s, %s, %s, %s, %s)"
            f" returning {_STORED}",
            (name, version, provider, description, subject)).fetchone()
        from platform_service.ledger import outbox

        outbox.emit_project(conn, "card_version.created", item_type="card_version", item_id=row["pid"],
                            item_version=row["number"],
                            details={"number": row["number"], "name": name, "version": version,
                                     "provider": provider})
    return _as_version(row, pid)


def list_versions(project: str) -> list[dict] | None:
    """Every saved card version of the project, highest number first. None: no such project."""
    pid = _resolve(project)
    if pid is None:
        return None
    with project_connection(pid) as conn:
        rows = conn.execute(f"select {_STORED} from project.system order by number desc").fetchall()
    return [_as_version(r, pid) for r in rows]


def latest_version(project: str) -> tuple[bool, dict | None]:
    """(whether the project exists, its highest-numbered card version or None)."""
    pid = _resolve(project)
    if pid is None:
        return False, None
    with project_connection(pid) as conn:
        row = conn.execute(f"select {_STORED} from project.system order by number desc limit 1").fetchone()
    return True, _as_version(row, pid)


def get_system(version_pid: str, project_pids: list[str]) -> dict | None:
    """One saved card version by its own id, looked for only in these projects'
    databases (the caller's, or every one for an admin: I2.3). A project whose
    database is gone, or has no project.system yet, is skipped."""
    for pid in project_pids:
        try:
            conn = project_connection(pid)
        except ProjectDatabaseGone:
            continue
        with conn:
            if conn.execute("select to_regclass('project.system') as t").fetchone()["t"] is None:
                continue
            row = conn.execute(f"select {_STORED}, updated_at from project.system where pid = %s",
                               (version_pid,)).fetchone()
        if row is not None:
            return _as_version(row, pid)
    return None


# ── membership ───────────────────────────────────────────────────────────────
# A project belongs to the people in it. Every query that returns a project, or
# anything inside one, passes through here: filtering in one place is what makes
# it hard to add an endpoint that forgets.


def _project_pid(conn, identifier: str) -> str | None:
    found = conn.execute(
        f"select pid from core.project where {_key_column(identifier)} = %s", (identifier,)
    ).fetchone()
    return found["pid"] if found else None


def role_in_project(project: str, subject: str) -> str | None:
    """What this person is to this project, or None if they are not in it."""
    column = _key_column(project)
    with pool().connection() as conn:
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
    column = _key_column(project)
    with pool().connection() as conn:
        return conn.execute(
            "select m.subject, m.email, m.role, m.added_at"
            "  from core.project_member m join core.project p on p.pid = m.project_id"
            f" where p.{column} = %s order by m.added_at",
            (project,),
        ).fetchall()


def add_member(project: str, subject: str, email: str | None, role: str) -> dict | None:
    """Put somebody in a project, or change what they are in it."""
    from platform_service.ledger import outbox

    with pool().connection() as conn, conn.transaction():
        pid = _project_pid(conn, project)
        if pid is None:
            return None
        before = conn.execute("select role from core.project_member where project_id = %s and subject = %s",
                              (pid, subject)).fetchone()
        row = conn.execute(
            "insert into core.project_member (project_id, subject, email, role)"
            " values (%s, %s, %s, %s)"
            " on conflict (project_id, subject) do update"
            "    set role = excluded.role,"
            "        email = coalesce(excluded.email, core.project_member.email)"
            " returning subject, email, role, added_at",
            (pid, subject, email, role),
        ).fetchone()
        if before is None:
            outbox.emit(conn, "member.added", project_pid=pid, item_type="member", item_id=subject,
                        details={"role": role})
        elif before["role"] != role:
            outbox.emit(conn, "member.role_changed", project_pid=pid, item_type="member", item_id=subject,
                        details={"role_before": before["role"], "role_after": role})
        return row


def owner_count(project: str) -> int:
    column = _key_column(project)
    with pool().connection() as conn:
        found = conn.execute(
            "select count(*) as n from core.project_member m"
            "  join core.project p on p.pid = m.project_id"
            f" where p.{column} = %s and m.role = 'owner'",
            (project,),
        ).fetchone()
        return found["n"]


def remove_member(project: str, subject: str) -> bool:
    from platform_service.ledger import outbox

    with pool().connection() as conn, conn.transaction():
        pid = _project_pid(conn, project)
        if pid is None:
            return False
        done = conn.execute(
            "delete from core.project_member where project_id = %s and subject = %s returning role",
            (pid, subject),
        ).fetchone()
        if done:
            outbox.emit(conn, "member.removed", project_pid=pid, item_type="member", item_id=subject,
                        details={"role": done["role"]})
        return done is not None


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
