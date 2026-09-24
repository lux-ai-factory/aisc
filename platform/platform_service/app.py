"""The platform API: the projects every module comes to reference.

Authentication is the gateway's job and is checked again here, because the
gateway's word is one hop away from a mistake. Authorisation is this service's
job, and it is the whole of it: a project belongs to the people in it, and
every endpoint that returns a project, or anything inside one, goes through the
same two questions. Is this person in it, and are they enough for this.

A stranger is answered 404 rather than 403. The slug of a project is its name,
often the name of a customer, and 403 would confirm it exists.
"""
from __future__ import annotations

import logging

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, Response
from psycopg import errors
from pydantic import BaseModel

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency, requires_role

from platform_service import dashboard_bridge, db, projectdb
from platform_service.membership import (
    InvalidMembership,
    at_least,
    may_manage_members,
    may_write,
    validate_role,
)
from platform_service.projects import InvalidProject, normalise_name, slug_for, validate_slug
from platform_service.systems import InvalidSystem, system_key

logger = logging.getLogger(__name__)

app = FastAPI(title="AISC platform", docs_url="/docs")

#: The realm role that administers the platform. It is not a membership: an
#: admin is not in the project, it may act on any of them, which is what makes
#: an orphaned project recoverable.
ADMIN_ROLE = "admin"


def no_project(identifier: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"no project {identifier!r}")


def effective_role(project: str, caller: Caller) -> str | None:
    """What this caller is to this project, counting the admin role."""
    if caller.has_role(ADMIN_ROLE):
        return "owner"
    return db.role_in_project(project, caller.subject)


def role_or_404(project: str, caller: Caller, needed: str = "viewer") -> str:
    """The caller's role, or the answer a stranger gets.

    404 for "not yours" and 403 for "not enough": a member is told they lack
    the rank, a non-member is told nothing at all.
    """
    role = effective_role(project, caller)
    if not at_least(role, "viewer"):
        raise no_project(project)
    if not at_least(role, needed):
        raise HTTPException(status_code=403, detail=f"this takes {needed} on this project")
    return role


def owner_or_403(project: str, caller: Caller) -> None:
    """Only an owner decides who is in a project."""
    if not may_manage_members(role_or_404(project, caller)):
        raise HTTPException(status_code=403, detail="only an owner decides who is in a project")


def refuse_losing_last_owner(project: str, subject: str) -> None:
    """A project with nobody in it is a project nobody can open, and the last
    owner leaving is the only way to make one."""
    if db.role_in_project(project, subject) == "owner" and db.owner_count(project) <= 1:
        raise HTTPException(status_code=409, detail="a project keeps at least one owner")


class ProjectIn(BaseModel):
    name: str
    slug: str | None = None
    description: str | None = None


class DeleteProjectIn(BaseModel):
    confirm_name: str


class MemberIn(BaseModel):
    subject: str
    email: str | None = None
    role: str = "viewer"


class MemberRoleIn(BaseModel):
    role: str


class SystemIn(BaseModel):
    name: str
    version: str | None = None
    provider: str | None = None
    description: str | None = None


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/projects")
def projects(caller: Caller = Depends(caller_dependency)) -> list[dict]:
    if caller.has_role(ADMIN_ROLE):
        return db.list_projects()
    return db.projects_for(caller.subject)


@app.get("/projects/{slug}")
def project(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return found


@app.post("/projects", status_code=201)
def add_project(body: ProjectIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """Anybody signed in may start an assessment, and owns the one they start."""
    name = normalise_name(body.name)
    slug = validate_slug(body.slug) if body.slug else slug_for(name)
    try:
        created = db.create_project(name, slug, body.description, caller.subject, caller.email)
    except errors.UniqueViolation:
        raise HTTPException(status_code=409, detail=f"a project {slug!r} already exists")
    provision_or_undo(created["pid"])
    if not dashboard_bridge.register(created["pid"], created["slug"], created["name"]):
        db.remember_unregistered(created["pid"])
    return created


def provision_or_undo(pid) -> None:
    """Make the project's database, or remove the project again.

    A project without its database is one every module fails on. CREATE
    DATABASE may have succeeded before the template step failed, so the
    database is dropped too; a failing drop is logged and does not mask the 503.
    """
    try:
        projectdb.provision(db.dsn(), pid)
    except Exception:
        db.delete_project(pid)
        try:
            projectdb.drop(db.dsn(), pid)
        except Exception:
            logger.exception("could not drop the half-made database of project %s; drop it by hand", pid)
        raise HTTPException(status_code=503, detail="the project's database could not be made; nothing was created")


@app.delete("/projects/{slug}", status_code=204)
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
    # The dashboard lets go of the project's database before it is dropped.
    dashboard_bridge.unregister(found["pid"])
    projectdb.drop(db.dsn(), found["pid"])
    db.delete_project(found["pid"])


# ── who is in a project ──────────────────────────────────────────────────────


@app.get("/authz/projects/{slug}")
def authorisation(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """What this caller may do here.

    The one endpoint that answers for strangers too, because it is what the
    other modules ask before deciding what to show, and "nothing" is an answer
    they need rather than an error they have to interpret.
    """
    role = effective_role(slug, caller)
    return {
        "role": role,
        "admin": caller.has_role(ADMIN_ROLE),
        "may_write": may_write(role),
    }


@app.get("/authz/admin", status_code=204)
def admin_gate(caller: Caller = Depends(requires_role(ADMIN_ROLE))) -> Response:
    """Whether this caller is an admin, for Caddy to ask with forward_auth.

    The database tools on the launcher see every project's database, so they
    are behind this rather than behind a membership: 204 lets the request
    through, 403 does not.
    """
    return Response(status_code=204)


@app.get("/projects/{slug}/members")
def project_members(slug: str, caller: Caller = Depends(caller_dependency)) -> list[dict]:
    role_or_404(slug, caller)
    return db.members(slug)


@app.post("/projects/{slug}/members", status_code=201)
def add_project_member(
    slug: str, body: MemberIn, caller: Caller = Depends(caller_dependency)
) -> dict:
    owner_or_403(slug, caller)
    added = db.add_member(slug, body.subject, body.email, validate_role(body.role))
    if added is None:
        raise no_project(slug)
    return added


@app.put("/projects/{slug}/members/{subject}")
def set_project_member_role(
    slug: str, subject: str, body: MemberRoleIn, caller: Caller = Depends(caller_dependency)
) -> dict:
    owner_or_403(slug, caller)
    wanted = validate_role(body.role)
    if wanted != "owner":
        refuse_losing_last_owner(slug, subject)
    changed = db.add_member(slug, subject, None, wanted)
    if changed is None:
        raise no_project(slug)
    return changed


@app.delete("/projects/{slug}/members/{subject}", status_code=204)
def remove_project_member(
    slug: str, subject: str, caller: Caller = Depends(caller_dependency)
) -> None:
    owner_or_403(slug, caller)
    refuse_losing_last_owner(slug, subject)
    if not db.remove_member(slug, subject):
        raise HTTPException(status_code=404, detail=f"{subject!r} is not in {slug!r}")


@app.post("/projects/{project}/system-versions", status_code=201)
def create_system_version(
    project: str, body: SystemIn, caller: Caller = Depends(caller_dependency)
) -> dict:
    """Save the AI card's next version: numbered 1, 2, ... per project, even
    when name and version repeat. Saving is changing the work: an editor."""
    role_or_404(project, caller, needed="editor")
    name, version = system_key(body.name, body.version)
    made = db.create_version(project, name, version, body.provider, body.description,
                             caller.subject)
    if made is None:
        raise no_project(project)
    return made


@app.get("/projects/{project}/system-versions")
def system_versions(project: str, caller: Caller = Depends(caller_dependency)) -> list[dict]:
    """Every saved card version, highest number first."""
    role_or_404(project, caller)
    found = db.list_versions(project)
    if found is None:
        raise no_project(project)
    return found


@app.get("/projects/{project}/system-versions/latest")
def latest_system_version(project: str, caller: Caller = Depends(caller_dependency)) -> dict | None:
    """The latest saved card version, or null when the project has none yet."""
    role_or_404(project, caller)
    exists, found = db.latest_version(project)
    if not exists:
        raise no_project(project)
    return found


@app.get("/systems/{pid}")
def system(pid: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """A system by its own id.

    The project is checked here too: an id that skips the project is exactly
    how a stranger would read one.
    """
    found = db.get_system(pid)
    if found is None:
        raise HTTPException(status_code=404, detail=f"no system {pid}")
    role_or_404(str(found["project_id"]), caller)
    return found


def invalid_input(_, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


for _invalid in (InvalidProject, InvalidSystem, InvalidMembership):
    app.add_exception_handler(_invalid, invalid_input)
