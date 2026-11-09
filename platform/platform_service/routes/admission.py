"""Who may call a route: the project-access rule against the platform's own pool, the
refusals every router answers with, and the ledger's check of a witnessed request."""
from __future__ import annotations

from aisc_identity import Caller
from aisc_identity.access import ADMIN_ROLE, Admitted, Refused, admit, at_least
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from platform_service import db, llm_store

# ADMIN_ROLE (aisc_identity.access) is the realm role that administers the platform. It is not a
# membership: an admin is not in the project, it may act on any of them, which is what makes an orphaned
# project recoverable. The routers import it from here.


def no_project(identifier: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"no project {identifier!r}")


def admitted(project: str, caller: Caller, want: str = "GET") -> Admitted:
    """aisc_identity.access.admit against the platform's own pool. `want` is a method, "manage" or a role."""
    return admit(project, caller, want, connect=db.pool().connection)


def role_or_404(project: str, caller: Caller, needed: str = "viewer") -> str:
    """The caller's role, or the refusal: 404 for a stranger, 403 for too low a rank."""
    try:
        return admitted(project, caller, needed).role
    except Refused as refused:
        raise HTTPException(status_code=refused.status, detail=refused.message) from None


def owner_or_403(project: str, caller: Caller) -> None:
    """Only an owner decides who is in a project."""
    role_or_404(project, caller, "owner")


def last_owner() -> HTTPException:
    """db.LastOwner as an answer: the check runs in the membership write itself (db.add_member,
    db.remove_member), under a lock on the project row."""
    return HTTPException(status_code=409, detail="a project keeps at least one owner")


def _internal(status: int, body: dict) -> JSONResponse:
    return JSONResponse(status_code=status, content=body, headers={"Cache-Control": "no-store"})


def _ledger_presented(request: Request, request_id: str | None) -> str | None:
    """Why this write may not go on in `enforce`, or None. The request id must be one the witness gave,
    for a verified person who is this caller; through the gateway directly, for this method and path."""
    from aisc_identity.service import NotAuthenticated, caller_from_headers

    from platform_service.ledger import actors, witness as ledger_witness

    if not request_id:
        return "a write needs the request the gateway witnessed (X-AISC-Request-Id)"
    rec = ledger_witness.record(request_id)
    if rec is None or not rec.verified:
        return "unknown or unverified request id"
    try:
        caller = caller_from_headers(request.headers)
    except NotAuthenticated:
        return None                                                   # the route answers 401 itself
    try:
        who = actors.resolve(rec.project_pid, rec.actor_ref)
    except actors.MappingAlarm:
        return "the request's person can't be checked"
    if who is None or who[0] != caller.subject:
        return "this request id was witnessed for someone else"
    if rec.app == "platform" and (rec.method != request.method or rec.route_path != "/api" + request.url.path):
        return "this request id was witnessed for another request"
    return None


def admin_project(slug: str, caller: Caller) -> dict:
    """The project, for a platform admin only: a stranger gets 404, a member 403."""
    role_or_404(slug, caller)
    if not caller.has_role(ADMIN_ROLE):
        raise HTTPException(status_code=403, detail="only a platform admin manages models and keys")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return found


def secrets_unavailable(exc: llm_store.SecretsKeyError) -> HTTPException:
    return HTTPException(status_code=503, detail=str(exc))


#: Who may do what with a project's connections, their uses, its model keys and its helper models: the rank each
#: action takes ("viewer", "editor", "owner" of the project, or "admin", a platform admin only). A platform admin
#: counts as owner of every project. The routes of connections.py, connectivity.py, helpers.py and llm.py name an
#: action, never a role (tests/test_admission_actions.py).
ACTIONS: dict[str, str] = {
    # Manage > Connections: the connections themselves, keys included
    "connection.read": "admin",
    "connection.write": "admin",
    "connection.test": "admin",
    "connection.protocols": "viewer",
    "target.read": "viewer",
    "target.sync": "editor",
    "target.file": "admin",
    "allowlist.read": "owner",
    "allowlist.write": "owner",
    # Manage > Connectivity: what a connection is used for
    "connectivity.read": "owner",
    "connectivity.settings": "admin",          # every connection's settings, beside its uses (an owner sees each
                                               # one's name, label, kind and uses only)
    "use.agent": "admin",                      # a Configurator agent's model, and the models offered for it
    "use.tool": "admin",                       # any connection without a target as a test tool: its key goes to plugins
    "use.tool.provider": "owner",              # a provider connection as a test tool, or a test tool stopped
    # model keys and the agents' choices (Manage > LLM)
    "llm.read": "admin",
    "llm.write": "admin",
    # helper models
    "helper.read": "viewer",
    "helper.write": "owner",
}


def project_for(slug: str, caller: Caller, action: str) -> dict:
    """The project, for a caller `action` admits (ACTIONS): a stranger gets 404, a lesser rank 403."""
    needed = ACTIONS[action]
    if needed == "admin":
        return admin_project(slug, caller)
    role_or_404(slug, caller, needed)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return found


def allowed_actions(slug: str, caller: Caller) -> set[str]:
    """The actions of ACTIONS this caller may take in the project (a member's view of what it may manage)."""
    try:
        seen = admitted(slug, caller)
    except Refused:
        return set()
    return {action for action, needed in ACTIONS.items()
            if (seen.admin if needed == "admin" else at_least(seen.role, needed))}
