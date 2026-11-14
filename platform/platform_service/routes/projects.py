"""Projects, their members, and the AI system each one assesses."""
from __future__ import annotations

import logging

import psycopg
from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from fastapi import APIRouter, Depends, HTTPException
from psycopg import errors
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field, StrictStr, field_validator

from platform_service import dashboard_bridge, db, projectdb, proof_store, targets
from platform_service.membership import validate_role
from platform_service.projects import normalise_name, slug_for, validate_slug
from platform_service.routes.admission import ADMIN_ROLE, last_owner, no_project, owner_or_403, role_or_404
from platform_service.systems import system_key

router = APIRouter()

logger = logging.getLogger(__name__)


# Each body takes only its own fields, as strings, each with an upper bound: an unknown field or an overlong
# text is a 422 and is never stored.
_STRICT = ConfigDict(extra="forbid")


class ProjectIn(BaseModel):
    model_config = _STRICT
    name: StrictStr = Field(max_length=200)
    slug: StrictStr | None = Field(default=None, max_length=64)
    description: StrictStr | None = Field(default=None, max_length=2000)


class DeleteProjectIn(BaseModel):
    model_config = _STRICT
    confirm_name: StrictStr = Field(max_length=200)


class MemberIn(BaseModel):
    model_config = _STRICT
    subject: StrictStr = Field(max_length=255)
    email: StrictStr | None = Field(default=None, max_length=320)
    role: StrictStr = Field(default="viewer", max_length=32)


class MemberRoleIn(BaseModel):
    model_config = _STRICT
    role: StrictStr = Field(max_length=32)


class SystemIn(BaseModel):
    model_config = _STRICT
    name: StrictStr = Field(max_length=200)
    version: StrictStr | None = Field(default=None, max_length=100)
    provider: StrictStr | None = Field(default=None, max_length=200)
    description: StrictStr | None = Field(default=None, max_length=2000)


class SystemRevisionIn(SystemIn):
    reason: str
    requested_by: str
    #: the card revision the correction started from (refused with 409 when it is no longer the current one)
    expected_card_revision: int

    @field_validator("reason", "requested_by")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


@router.get("/projects")
def projects(caller: Caller = Depends(caller_dependency)) -> list[dict]:
    if caller.has_role(ADMIN_ROLE):
        return db.list_projects()
    return db.projects_for(caller.subject)


@router.get("/projects/{slug}")
def project(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return found


@router.post("/projects", status_code=201)
def add_project(body: ProjectIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """Anybody signed in may start an assessment, and owns the one they start."""
    name = normalise_name(body.name)
    slug = validate_slug(body.slug) if body.slug else slug_for(name)
    try:
        created = db.create_project(name, slug, body.description, caller.subject, caller.email)
    except errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"a project {slug!r} already exists")
    provision_or_undo(created["pid"])
    # every evaluation names a target: the system's exists from the start (targets plan v2);
    # its engine mirror follows on the first pass that has a caller's token and an engine project
    try:
        targets.ensure_system(created["pid"], created["name"])
    except Exception:
        # never a reason to refuse the project: the targets list, every sync and the engine's
        # evaluation form ensure it again
        logger.exception("the system target of project %s was not made at creation", created["pid"])
    if not dashboard_bridge.register(created["pid"], created["slug"], created["name"]):
        db.remember_unregistered(created["pid"])
    return created


def provision_or_undo(pid) -> None:
    """Make the project's database and its bucket for proof files, or remove the project again.

    A project without its database is one every module fails on. CREATE
    DATABASE may have succeeded before the template step failed, so the
    database is dropped too; a failing drop is logged and does not mask the 503.
    The bucket is made last, so a bucket that cannot be made leaves nothing
    behind either.
    """
    try:
        projectdb.provision(db.migrate_dsn(), pid)
        proof_store.make_project_bucket(pid)
    except Exception:
        db.delete_project(pid)
        try:
            projectdb.drop(db.migrate_dsn(), pid)
        except Exception:
            logger.exception("could not drop the half-made database of project %s; drop it by hand", pid)
        raise HTTPException(status_code=503, detail="the project's database could not be made; nothing was created")


@router.delete("/projects/{slug}", status_code=204)
def remove_project(slug: str, body: DeleteProjectIn, caller: Caller = Depends(caller_dependency)) -> None:
    """Delete a project and everything every module holds for it.

    Only an admin, and only by typing the project's name exactly: this drops the
    project's database, and there is no undo. The database goes first, so a
    failure halfway leaves a project with no data rather than data with no
    project.
    """
    if not caller.has_role(ADMIN_ROLE):
        role_or_404(slug, caller)  # a stranger is told nothing
        raise HTTPException(status_code=403, detail="only an admin deletes a project")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    if body.confirm_name != found["name"]:
        raise HTTPException(status_code=422, detail="type the project's name exactly to delete it")
    closed_to = _ledger_drain_or_refuse(found["pid"])
    # The dashboard lets go of the project's database before it is dropped.
    dashboard_bridge.unregister(found["pid"])
    try:
        projectdb.drop(db.migrate_dsn(), found["pid"])
    except Exception as exc:
        # the project is still there with its data: the apps may connect again and its dashboard comes back
        _reopen(found["pid"], closed_to)
        if not dashboard_bridge.register(found["pid"], found["slug"], found["name"]):
            db.remember_unregistered(found["pid"])
        if isinstance(exc, errors.InsufficientPrivilege):
            logger.error("project %s: its database can't be dropped while apps hold sessions: platform_migrator may"
                         " not end them (postgres-setup applies init/owner-roles.sql)", found["pid"])
            raise HTTPException(status_code=503, detail="the project's database is in use and can't be closed now:"
                                " the platform's database role is not set up to close it") from None
        raise
    db.delete_project(found["pid"])
    # its proof files go with it; the project is gone either way, so a bucket left behind is only logged
    try:
        proof_store.remove_project_bucket(found["pid"])
    except Exception:
        logger.exception("project %s: its proof-file bucket %s could not be removed; remove it by hand",
                         found["pid"], proof_store.bucket_name(found["pid"]))


def _reopen(pid, grantees: list[str]) -> None:
    """Give CONNECT back to the roles the drain took it from. Never raises: a failure is logged with
    the roles, which then need `GRANT CONNECT` by hand."""
    name = projectdb.database_name(pid)
    try:
        with psycopg.connect(db.migrate_dsn(), autocommit=True) as conn:
            for grantee in grantees:
                conn.execute(f'GRANT CONNECT ON DATABASE "{name}" TO {grantee}')
    except Exception:
        logger.exception("project %s: CONNECT could not be given back to %s", pid, ", ".join(grantees))


def _ledger_drain_or_refuse(pid) -> list[str]:
    """Before a project database is dropped, its outbox must be in the log, and so must the engine's own
    outbox there (aisc-backend-ledger sends it): the drop would destroy what hasn't been delivered.
    Platform-database rows (members, this delete's own event) don't block: they outlive the drop.

    No event may commit after the count: CONNECT is revoked first, so no new app session starts, and the
    apps' sessions are ended (as platform_migrator, the database's owner, through
    aisc_setup.end_project_sessions); a session that is still there makes the delete wait (409), since it could
    still commit. platform_rw keeps CONNECT: it counts the outbox. A count that fails while the database exists
    is never "nothing to lose" (503). On a refusal the database is opened again.

    Returns the roles CONNECT was taken from, for the caller to give it back if the drop then fails."""
    from platform_service.ledger import relay
    from platform_service.ledger import witness as ledger_witness
    from platform_service.ledger.store import LedgerError

    if ledger_witness.mode() == "off":
        return []
    from platform_service.ledger import provision

    if provision.database_for(str(pid)) is None:
        # its events (this delete's own included) would have no log to go to, for ever
        raise HTTPException(status_code=409, detail="the project has no ledger yet (the pool was empty when it was"
                            " made): it gets one at the stack's next start, or now with scripts/ledger-pool.sh")
    name = projectdb.database_name(pid)
    with psycopg.connect(db.migrate_dsn(), autocommit=True, row_factory=dict_row) as conn:
        if conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is None:
            return []                                                 # no project database: nothing to lose
        # every role that may connect but the owner and the platform's own (each module role has its own grant,
        # PUBLIC may too)
        grantees = [r["grantee"] for r in conn.execute(
            "SELECT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE quote_ident(r.rolname) END AS grantee"
            " FROM pg_database d CROSS JOIN LATERAL aclexplode(d.datacl) a LEFT JOIN pg_roles r ON r.oid = a.grantee"
            " WHERE d.datname = %s AND a.privilege_type = 'CONNECT' AND a.grantee <> d.datdba"
            " AND r.rolname IS DISTINCT FROM 'platform_rw'", (name,))]
        for grantee in grantees:
            conn.execute(f'REVOKE CONNECT ON DATABASE "{name}" FROM {grantee}')
    try:
        import time

        for _ in range(10):
            with psycopg.connect(db.migrate_dsn(), autocommit=True, row_factory=dict_row) as conn:
                # no new session can start (CONNECT is revoked); the apps' pooled ones are ended, so none
                # can commit an event after the count
                conn.execute("SELECT aisc_setup.end_project_sessions(%s)", (name,))
                others = conn.execute("SELECT count(*) AS n FROM pg_stat_activity WHERE datname = %s"
                                      " AND usename <> 'platform_rw'", (name,)).fetchone()["n"]
            if not others:
                break
            time.sleep(0.2)
        if others:
            raise HTTPException(status_code=409, detail="the project's database is still in use by an app: try again")
        try:
            relay.relay_once(str(pid))
        except LedgerError:
            pass                                                      # counted below
        try:
            with projectdb_connection(pid) as conn:
                left = conn.execute("SELECT count(*) AS n FROM ledger.outbox o LEFT JOIN ledger.delivered d"
                                    " ON d.event_id = o.event_id WHERE d.event_id IS NULL").fetchone()["n"]
                engine_left = _engine_left(conn)
        except Exception:
            logger.exception("project %s: the undelivered events could not be counted", pid)
            raise HTTPException(status_code=503, detail="the project's undelivered events could not be counted:"
                                " nothing was deleted") from None
        if left:
            raise HTTPException(status_code=409, detail=f"the log still has {left} undelivered events: try again soon")
        if engine_left:
            # aisc-backend-ledger sends them once the database is open again (the refusal below reopens it)
            raise HTTPException(status_code=409, detail=f"the engine still has {engine_left} events to send to the log:"
                                " try again soon")
    except HTTPException:
        _reopen(pid, grantees)                                        # refused: the apps may connect again
        raise
    return grantees


def _engine_left(conn) -> int:
    """The engine's events still to send from this project database (its own outbox, migration 0023), or 0
    where the engine has no outbox there yet."""
    if conn.execute("SELECT to_regclass('engine.aisc_backend_ledgeroutbox') AS t").fetchone()["t"] is None:
        return 0
    return conn.execute("SELECT count(id) AS n FROM engine.aisc_backend_ledgeroutbox"
                        " WHERE delivered_at IS NULL AND refused IS NULL").fetchone()["n"]


def projectdb_connection(pid):
    return projectdb.connect(pid)


@router.get("/projects/{slug}/members")
def project_members(slug: str, caller: Caller = Depends(caller_dependency)) -> list[dict]:
    role_or_404(slug, caller)
    return db.members(slug)


@router.post("/projects/{slug}/members", status_code=201)
def add_project_member(
    slug: str, body: MemberIn, caller: Caller = Depends(caller_dependency)
) -> dict:
    owner_or_403(slug, caller)
    try:
        added = db.add_member(slug, body.subject, body.email, validate_role(body.role))
    except db.LastOwner:
        raise last_owner() from None
    if added is None:
        raise no_project(slug)
    return added


@router.put("/projects/{slug}/members/{subject}")
def set_project_member_role(
    slug: str, subject: str, body: MemberRoleIn, caller: Caller = Depends(caller_dependency)
) -> dict:
    owner_or_403(slug, caller)
    try:
        changed = db.add_member(slug, subject, None, validate_role(body.role))
    except db.LastOwner:
        raise last_owner() from None
    if changed is None:
        raise no_project(slug)
    return changed


@router.delete("/projects/{slug}/members/{subject}", status_code=204)
def remove_project_member(
    slug: str, subject: str, caller: Caller = Depends(caller_dependency)
) -> None:
    owner_or_403(slug, caller)
    try:
        removed = db.remove_member(slug, subject)
    except db.LastOwner:
        raise last_owner() from None
    if not removed:
        raise HTTPException(status_code=404, detail=f"{subject!r} is not in {slug!r}")


@router.post("/projects/{project}/system-versions", status_code=201)
def create_system_version(
    project: str, body: SystemIn, caller: Caller = Depends(caller_dependency)
) -> dict:
    """Save the AI card's next version: numbered 1, 2, ... per project, even
    when name and version repeat. Saving is changing the work: an editor."""
    role_or_404(project, caller, needed="editor")
    name, version = system_key(body.name, body.version)
    try:
        made = db.create_version(project, name, version, body.provider, body.description,
                                 caller.subject)
    except db.ProjectDatabaseGone:
        raise no_project(project) from None
    if made is None:
        raise no_project(project)
    return made


@router.patch("/projects/{project}/system-versions/{pid}")
def revise_system_version(
    project: str, pid: str, body: SystemRevisionIn, caller: Caller = Depends(caller_dependency)
) -> dict:
    """Correct the description of the latest card version without making a new one: same pid and number,
    card_revision one higher. Needs a reason, who asked, and the card revision it started from (409 when
    another correction came first). Changing the work: an editor."""
    role_or_404(project, caller, needed="editor")
    name, version = system_key(body.name, body.version)
    try:
        revised = db.revise_version(project, pid, name, version, body.provider, body.description,
                                    body.reason, body.requested_by, caller.subject,
                                    expected_card_revision=body.expected_card_revision)
    except db.ProjectDatabaseGone:
        raise no_project(project) from None
    except db.NoSuchVersion:
        raise HTTPException(status_code=404, detail=f"no version {pid!r} in {project!r}") from None
    except db.NotLatest:
        raise HTTPException(status_code=409, detail="only the latest version, as last corrected, can be revised:"
                                                    " reload it") from None
    if revised is None:
        raise no_project(project)
    return revised


@router.get("/projects/{project}/system-versions")
def system_versions(project: str, caller: Caller = Depends(caller_dependency)) -> list[dict]:
    """Every saved card version, highest number first."""
    role_or_404(project, caller)
    try:
        found = db.list_versions(project)
    except db.ProjectDatabaseGone:
        raise no_project(project) from None
    if found is None:
        raise no_project(project)
    return found


@router.get("/projects/{project}/system-versions/latest")
def latest_system_version(project: str, caller: Caller = Depends(caller_dependency)) -> dict | None:
    """The latest saved card version, or null when the project has none yet."""
    role_or_404(project, caller)
    try:
        exists, found = db.latest_version(project)
    except db.ProjectDatabaseGone:
        raise no_project(project) from None
    if not exists:
        raise no_project(project)
    return found
