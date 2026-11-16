"""Each project's allowed internal hosts."""
from __future__ import annotations

import logging

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, StrictStr

from platform_service import (connection_allowlist)
from platform_service.routes.admission import project_for

router = APIRouter()

logger = logging.getLogger(__name__)


# ── Allowed internal hosts ────────────────────────────────────────────────────
# Per project; its owners and platform admins edit it. The deployment's CONNECTIONS_ALLOWED_HOSTS
# is a floor shown read-only; the stack's own services, loopback and metadata are never allowed
# here (connection_allowlist).

class AllowedHostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: StrictStr | None = None


def _allowed_view(row: dict) -> dict:
    return {"host": row["host"], "note": row["note"], "updated_by": row["updated_by"],
            "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
            "denied": connection_allowlist.why_denied(row["host"])}


def _entry_or_422(entry: str) -> str:
    try:
        return connection_allowlist.normalise(entry)
    except connection_allowlist.InvalidEntry as exc:
        raise HTTPException(status_code=422, detail=f"{entry!r}: {exc}") from None


def _not_the_floor(host: str) -> None:
    if host in {connection_allowlist.normalise(h) for h in connection_allowlist.floor()
                if connection_allowlist._valid(h)}:
        raise HTTPException(status_code=409, detail=f"{host} is allowed by the deployment (CONNECTIONS_ALLOWED_HOSTS)"
                                                    " and is changed there, not here")


@router.get("/projects/{slug}/allowed-hosts")
def list_allowed_hosts(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    pid = project_for(slug, caller, "allowlist.read")["pid"]
    return {"floor": connection_allowlist.floor(),
            "entries": [_allowed_view(r) for r in connection_allowlist.entries(pid)]}


@router.put("/projects/{slug}/allowed-hosts/{entry}")
def put_allowed_host(slug: str, entry: str, body: AllowedHostIn,
                     caller: Caller = Depends(caller_dependency)) -> dict:
    pid = project_for(slug, caller, "allowlist.write")["pid"]
    host = _entry_or_422(entry)
    _not_the_floor(host)
    note = (body.note or "").strip() or None
    if note is not None and len(note) > 200:
        raise HTTPException(status_code=422, detail="note: up to 200 characters")
    try:
        row = connection_allowlist.put(pid, host, note, caller.username or caller.subject)
    except connection_allowlist.DeniedEntry as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    logger.info("project %s allows %s for its connections", pid, host)
    return _allowed_view(row)


@router.delete("/projects/{slug}/allowed-hosts/{entry}", status_code=204)
def delete_allowed_host(slug: str, entry: str, caller: Caller = Depends(caller_dependency)) -> Response:
    pid = project_for(slug, caller, "allowlist.write")["pid"]
    host = _entry_or_422(entry)
    _not_the_floor(host)
    if not connection_allowlist.remove(pid, host):
        raise HTTPException(status_code=404, detail=f"{host} is not allowed in this project")
    logger.info("project %s no longer allows %s", pid, host)
    return Response(status_code=204)
