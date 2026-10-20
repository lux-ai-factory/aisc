"""The gateway's questions: may this person reach this project, this admin page, this schema;
and the witness of each request."""
from __future__ import annotations

import re
import uuid
from urllib.parse import parse_qs, unquote, urlsplit

from aisc_identity import Caller
from aisc_identity.access import Refused
from aisc_identity.fastapi import caller_dependency, requires_role
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from platform_service import db
from platform_service.routes.admission import ADMIN_ROLE, admitted

router = APIRouter()


@router.get("/authz/projects/{ref}")
def authorisation(ref: str, want: str = "GET", caller: Caller = Depends(caller_dependency)) -> dict:
    """What this caller may do in a project, for the apps that do not decide it themselves.

    Always 200: a refusal is an answer the asking app needs, carried in `verdict`
    and `status`. `want` is the HTTP method the app is about to serve, or "manage".
    """
    try:
        found = admitted(ref, caller, want)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    except Refused as refused:
        return {"verdict": refused.code, "status": refused.status, "message": refused.message,
                "pid": None, "slug": None, "role": None, "admin": caller.has_role(ADMIN_ROLE),
                "may_write": False}
    return {"verdict": "allow", "status": 200, "message": None, "pid": found.pid, "slug": found.slug,
            "role": found.role, "admin": found.admin, "may_write": found.may_write}


@router.get("/authz/witness")
def ledger_witness(request: Request) -> Response:
    """The ledger's witness, for Caddy's forward_auth.
    Never served to a browser: the launcher answers 404 to /api/authz/*, and a call without the
    gateway secret gets 401. Off unless LEDGER_MODE says otherwise."""
    from platform_service.ledger.witness import witness

    answer = witness(request.headers)
    return Response(status_code=answer.status, headers=answer.headers)


@router.get("/authz/admin", status_code=204)
def admin_gate(caller: Caller = Depends(requires_role(ADMIN_ROLE))) -> Response:
    """Whether this caller is an admin, for Caddy to ask with forward_auth.

    The database tools on the launcher see every project's database, so they
    are behind this rather than behind a membership: 204 lets the request
    through, 403 does not.
    """
    return Response(status_code=204)


#: What /inspect/schema serves: the landing page, the shared database and project databases.
SCHEMA_DATABASE = re.compile(r"^(platform|project_([0-9a-f]{32}))$")


@router.get("/authz/schema", status_code=204)
def schema_gate(request: Request, caller: Caller = Depends(caller_dependency)) -> Response:
    """Whether this caller may see the database diagrams Caddy was asked for.

    The diagrams show structure, never rows, so they are for project members, not only
    admins: the landing page and the shared platform's diagrams to anyone signed in, a
    project's own database to its members. Only an admin may force a new SchemaSpy run
    (?refresh=1). Caddy passes the path in X-Forwarded-Uri, with or without the
    /inspect/schema prefix it strips. The path is judged decoded: a "." or ".." segment
    (also as %2e%2e), a "%" left after decoding, a backslash, a NUL, or a first segment
    that decodes to another name is 403."""
    parts = urlsplit(request.headers.get("x-forwarded-uri", "/"))
    path = parts.path.removeprefix("/inspect/schema")
    admin = caller.has_role(ADMIN_ROLE)
    refused = HTTPException(status_code=403, detail="these diagrams are not yours to see")
    if "refresh" in parse_qs(parts.query) and not admin:
        raise refused
    # The diagram server decodes the path once, and Caddy cleans a literal ".." but not
    # "%2e%2e": judge the decoded path, and refuse whatever decodes into a climb, a second
    # encoding, a backslash or a NUL, or a first segment that decodes to another name.
    decoded = unquote(path)
    if any(c in decoded for c in "%\\\x00"):
        raise refused
    raw_segments = [s for s in path.split("/") if s]
    segments = [s for s in decoded.split("/") if s]
    if not segments:
        return Response(status_code=204)
    if ".." in segments or "." in segments or raw_segments[0] != segments[0]:
        raise refused
    found = SCHEMA_DATABASE.fullmatch(segments[0])
    if found is None:
        raise refused
    if found.group(2) is None:
        return Response(status_code=204)
    pid = str(uuid.UUID(found.group(2)))
    if db.get_project(pid) is None:
        raise refused
    if not admin:
        try:
            admitted(pid, caller)
        except Refused:
            raise refused from None
    return Response(status_code=204)
