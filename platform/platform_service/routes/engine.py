"""Routes the engine backend calls, with a token of its own (PLATFORM_ENGINE_TOKEN).

Before the engine stores an evaluation it asks whether the card target picked can be reached: a
plugin that calls its target cannot run on one without a connection. The answer says only whether
there is a connection and its protocol, never the connection's key: the engine does not run plugins
and is not given what they call with.

The engine also lists the project's helper models for its run form, and, once, hands over the `llm`
components older runs used as helpers (manage.py move_helper_models) so they become helper models here."""
from __future__ import annotations

from urllib.parse import urlsplit

from aisc_identity.service_tokens import HEADER as SERVICE_TOKEN_HEADER, ServiceRefused, identify
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import StrictStr

from platform_service import connection_store, db, helper_store, llm_store, target_store, targets
from platform_service.projects import looks_like_pid
from platform_service.routes.admission import _internal
from platform_service.routes.connections import _behind_gateway
from platform_service.routes.helpers import HelperIn, helper_view, known_name, reachable
from platform_service.routes.llm import clean_base_url, clean_key

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


class MovedHelperIn(HelperIn):
    name: StrictStr


#: Who the platform records as having saved a helper the engine handed over.
MOVED_BY = "engine"


@router.post("/internal/projects/{pid}/helpers")
def create_helper(pid: str, body: MovedHelperIn, request: Request) -> JSONResponse:
    """A new helper model from the engine: an `llm` component older runs used as a helper, with its key.
    200 with the live helper that has the same label and endpoint, left as it is (the same component,
    moved before); 409 when a live helper has the name already (the engine then tries another). The answer is the
    helper as a page sees it, plus its reference; never the key."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    try:
        identify(request.headers.get(SERVICE_TOKEN_HEADER), {"engine": "PLATFORM_ENGINE_TOKEN"})
    except ServiceRefused as refused:
        return _internal(refused.status, {"detail": refused.detail})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    try:
        known_name(body.name)
        roles = list(dict.fromkeys(body.roles))
        label = body.label.strip()
        if not 1 <= len(label) <= 120:
            return _internal(422, {"detail": "label: 1 to 120 characters"})
        endpoint = clean_base_url(body.endpoint_url)
        if endpoint is None:
            return _internal(422, {"detail": "the endpoint must be http(s)://host[:port][/path]"})
        reachable(pid, endpoint)
        key = clean_key(body.api_key) if body.api_key and body.api_key.strip() else None
    except HTTPException as refused:
        return _internal(refused.status_code, {"detail": refused.detail})
    # a move whose answer was lost: this component's helper is there already, under whatever name it got
    already = next((h for h in helper_store.list_models(pid)
                    if h["label"] == label and h["endpoint_url"] == endpoint), None)
    if already is not None:
        return _internal(200, {**helper_view(already), "ref": f"helper:{pid}/{already['name']}"})
    if helper_store.get(pid, body.name) is not None:
        return _internal(409, {"detail": f"a helper is named {body.name!r} already"})
    try:
        ciphertext = llm_store.encrypt(key) if key else None
    except llm_store.SecretsKeyError as exc:
        return _internal(503, {"detail": str(exc)})
    from platform_service.ledger import secrets as ledger_secrets, witness as ledger_witness

    fingerprint = ledger_secrets.fingerprint(pid, key) if key and ledger_witness.mode() != "off" else None
    row = helper_store.save(pid, body.name, label=label, endpoint_url=endpoint, roles=roles,
                            ciphertext=ciphertext, subject=MOVED_BY, key_fingerprint=fingerprint)
    return _internal(201, {**helper_view(row), "ref": f"helper:{pid}/{row['name']}"})
