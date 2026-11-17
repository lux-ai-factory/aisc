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

from platform_service import connection_allowlist, connection_store, db, helper_store, llm_catalogue, llm_store, target_store, targets
from platform_service.projects import looks_like_pid
from platform_service.routes.admission import _internal
from platform_service.connections import CONNECTION_NAME, _fingerprint_of, descriptor_of
from platform_service.routes.run_passes import _behind_gateway

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


@router.get("/internal/projects/{pid}/helpers/{name}/models")
def helper_models(pid: str, name: str, request: Request) -> JSONResponse:
    """The models a test tool can run, asked live with its own connection, chat models first, for the run form:
    {"models": [...], "error": None} or {"models": [], "error": why}. The key is decrypted here only and never
    answered; the listing keeps llm_catalogue's limits (time, size, count, no redirect, no proxy)."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    try:
        identify(request.headers.get(SERVICE_TOKEN_HEADER), {"engine": "PLATFORM_ENGINE_TOKEN"})
    except ServiceRefused as refused:
        return _internal(refused.status, {"detail": refused.detail})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    target = helper_store.listing_of(pid, name)
    if target is None or target["provider"] not in llm_catalogue.PROVIDERS:
        return _internal(404, {"detail": f"no test tool {name!r}"})
    try:
        key = llm_store.decrypt(name, target["ciphertext"]) if target["ciphertext"] else None
    except (llm_store.KeyUnreadable, llm_store.SecretsKeyError) as exc:
        return _internal(200, {"models": [], "error": str(exc)})
    listed = llm_catalogue.list_models(target["provider"], api_key=key, base_url=target["base_url"],
                                       rule=connection_allowlist.rule(
                                           pid, operator_hosts=llm_store.operator_hosts(target["base_url"])))
    return _internal(200, {"models": llm_catalogue.chat_first(listed["models"]), "error": listed["error"]})


@router.get("/internal/projects/{pid}/network-rule")
def network_rule(pid: str, request: Request) -> JSONResponse:
    """The project's network rule, for the engine to send an LLM component's key only where the platform would send
    its own: {"allowed_hosts", "denied_addresses", "floor_hosts"} (connection_allowlist.rule). No key, no endpoint."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    try:
        identify(request.headers.get(SERVICE_TOKEN_HEADER), {"engine": "PLATFORM_ENGINE_TOKEN"})
    except ServiceRefused as refused:
        return _internal(refused.status, {"detail": refused.detail})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    return _internal(200, connection_allowlist.rule(pid))


#: The most references one fingerprints question may name (a run names a few).
MOST_FINGERPRINT_REFS = 32


def _reference(pid: str, ref) -> tuple[str, str] | None:
    """("target" or "connection", key or name) of `connection:<name>`, `target:<key>`, or either with this
    project's pid before the name (`target:<pid>/<key>`, as the engine and the worker write them); None otherwise."""
    if not isinstance(ref, str) or ":" not in ref:
        return None
    kind, _, rest = ref.partition(":")
    owner, slash, name = rest.rpartition("/")
    if slash and owner.lower() != str(pid).lower():
        return None
    if kind == "target" and targets.is_key(name):
        return kind, name
    if kind == "connection" and CONNECTION_NAME.fullmatch(name):
        return kind, name
    return None


@router.post("/internal/projects/{pid}/connections/fingerprints")
def connection_fingerprints(pid: str, body: dict, request: Request) -> JSONResponse:
    """Which endpoint each connection or target a run names would reach now, for the start of the run in the
    ledger: {"connections": [{"ref", "connection", "kind", "endpoint_sha256"}]}, the fingerprint a run key and a
    recorded use carry, never the key or the endpoint. A target with no endpoint has nulls. 404 for a
    reference the project does not have, 410 for a deleted connection, 422 for more than 32 references."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    try:
        identify(request.headers.get(SERVICE_TOKEN_HEADER), {"engine": "PLATFORM_ENGINE_TOKEN"})
    except ServiceRefused as refused:
        return _internal(refused.status, {"detail": refused.detail})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    refs = body.get("refs") if isinstance(body, dict) else None
    if not isinstance(refs, list) or len(refs) > MOST_FINGERPRINT_REFS:
        return _internal(422, {"detail": f"refs: a list of at most {MOST_FINGERPRINT_REFS} references"})
    answer = []
    for ref in refs:
        parsed = _reference(pid, ref)
        if parsed is None:
            return _internal(422, {"detail": f"not a target or connection reference of this project: {ref!r}"})
        kind, name = parsed
        if kind == "target":
            if target_store.get(pid, name) is None:
                return _internal(404, {"detail": f"no target {name!r}"})
            name = connection_store.holder_of(pid, name)
            if name is None:
                answer.append({"ref": ref, "connection": None, "kind": None, "endpoint_sha256": None})
                continue
        row = connection_store.descriptor(pid, name)
        if row is None:
            return _internal(404, {"detail": f"no connection {name!r}"})
        if row["deleted_at"] is not None:
            return _internal(410, {"detail": f"connection {name!r} was deleted"})
        answer.append({"ref": ref, "connection": row["name"], "kind": row["kind"],
                       "endpoint_sha256": _fingerprint_of(descriptor_of(row, pid))})
    return _internal(200, {"connections": answer})
