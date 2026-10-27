"""Routes the engine backend calls, with a token of its own (PLATFORM_ENGINE_TOKEN).

Before the engine stores an evaluation it asks whether the card target picked can be reached: a
plugin that calls its target cannot run on one without a connection. The answer says only whether
there is a connection and its protocol, never the connection's key: the engine does not run plugins
and is not given what they call with."""
from __future__ import annotations

from urllib.parse import urlsplit

from aisc_identity.service_tokens import HEADER as SERVICE_TOKEN_HEADER, ServiceRefused, identify
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from platform_service import connection_store, db, helper_store, target_store, targets
from platform_service.projects import looks_like_pid
from platform_service.routes.admission import _internal
from platform_service.routes.connections import _behind_gateway

router = APIRouter()


@router.get("/internal/projects/{pid}/targets/{key}/reachable")
def target_reachable(pid: str, key: str, request: Request) -> JSONResponse:
    """{"connected": bool, "protocol": the connection's kind or None} for a target of the project."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    try:
        identify(request.headers.get(SERVICE_TOKEN_HEADER), {"engine": "PLATFORM_ENGINE_TOKEN"})
    except ServiceRefused as refused:
        return _internal(refused.status, {"detail": refused.detail})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    if not targets.is_key(key) or target_store.get(pid, key) is None:
        return _internal(404, {"detail": f"no target {key!r}"})
    endpoint = connection_store.endpoints_by_target(pid).get(key)
    return _internal(200, {"connected": endpoint is not None, "protocol": endpoint["kind"] if endpoint else None})


@router.get("/internal/projects/{pid}/helpers")
def list_helpers(pid: str, request: Request, role: str | None = None) -> JSONResponse:
    """The project's helper models a test may pick, by reference: name, label, roles and the endpoint's
    host, never the full endpoint or a key (the worker resolves those with its own token)."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    try:
        identify(request.headers.get(SERVICE_TOKEN_HEADER), {"engine": "PLATFORM_ENGINE_TOKEN"})
    except ServiceRefused as refused:
        return _internal(refused.status, {"detail": refused.detail})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    if role is not None and role not in helper_store.ROLES:
        return _internal(422, {"detail": f"no role {role!r}"})
    return _internal(200, {"helpers": [
        {"name": h["name"], "label": h["label"], "roles": list(h["roles"]), "ref": f"helper:{pid}/{h['name']}",
         "endpoint_host": urlsplit(h["endpoint_url"]).hostname or ""}
        for h in helper_store.list_models(pid, role)]})
