"""Manage → Connections: list, save, link to a target, test and delete a project's connections, and the
internal routes that resolve one by name and issue its run keys. The rules of a connection live in
platform_service.connections; the targets, the run passes and the allowed hosts have routers of their own."""
from __future__ import annotations

import json
import logging

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from aisc_identity.headers import token_from_headers
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from psycopg import errors
from pydantic import BaseModel, ConfigDict, StrictStr

from platform_service import (adapters, connection_allowlist, connection_facade, connection_store, db, llm_store,
                              run_passes, secret_box, target_store, targets)
from platform_service.connections import (_PROBE_ERRORS, CONNECTION_NAME, ConnectionIn, _capability_checks,
                                          _fingerprint_of, _invalid_connection, _merged_secret_headers,
                                          _reached_by_ping, call_descriptor_of, connection_fields, connection_view,
                                          descriptor_of, retire_engine_component, secret_values)
from platform_service.routes.admission import _internal, project_for, secrets_unavailable
from platform_service.routes.run_passes import _internal_gate, _issue_run_key, _record_use

router = APIRouter()

logger = logging.getLogger(__name__)


class ProbeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # text for a chat system, or a JSON object for a structured one (a scorer takes an applicant)
    input: StrictStr | dict = "ping"


def admin_connection(slug: str, caller: Caller, name: str, action: str = "connection.write") -> str:
    pid = project_for(slug, caller, action)["pid"]
    if not CONNECTION_NAME.fullmatch(name):
        raise HTTPException(status_code=422, detail="name: lower-case letters, digits and hyphens, up to 63")
    return pid


def _with_pid(pid: str, row: dict | None) -> dict | None:
    return {**row, "pid": pid} if row else row


@router.get("/projects/{slug}/connections")
def list_connections(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    pid = project_for(slug, caller, "connection.read")["pid"]
    return {"connections": [connection_view(_with_pid(pid, r)) for r in connection_store.list_connections(pid)]}


def target_set_once() -> HTTPException:
    return HTTPException(status_code=422, detail="target: what a connection reaches is set once; create a new "
                                                 "connection to reach another one")


def used_connection(name: str) -> HTTPException:
    return HTTPException(status_code=409, detail=f"{name} is used as a test tool or by an agent: it cannot reach the "
                                                 "assessed system")


def other_kind(name: str) -> HTTPException:
    return HTTPException(status_code=409, detail=f"{name} is a connection of another kind; choose another name")


def checked_target(pid: str, name: str, key: str, before: dict | None) -> str:
    """`key`, once it may be the target of connection `name` (`before`: its stored row, or None): 422 unless it
    is the system or a component of this project, 422 when the connection already reaches another target (set
    once), 409 when another connection reaches it."""
    if not targets.is_key(key) or target_store.get(pid, key) is None:
        raise HTTPException(status_code=422, detail=f"target: {key!r} is not the system or a component of this project")
    if before and before.get("target_key") and before["target_key"] != key:
        raise target_set_once()
    holder = connection_store.holder_of(pid, key)
    if holder is not None and holder != name:
        raise HTTPException(status_code=409, detail=f"target: {key} already has a connection, {holder}")
    return key


@router.get("/projects/{slug}/connections/protocols")
def list_protocols(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    """The protocols a connection can use: the built-in ones, then each installed adapter with the fields its
    connection editor asks for (never a value)."""
    project_for(slug, caller, "connection.protocols")
    built_in = [{"name": kind, "label": targets.PROTOCOL_NAMES[kind], "adapter": False}
                for kind in adapters.BUILT_IN_KINDS]
    return {"protocols": built_in + [a.public() for _, a in sorted(adapters.registry().items())]}


@router.put("/projects/{slug}/connections/{name}")
def save_connection(slug: str, name: str, body: ConnectionIn, request: Request,
                    caller: Caller = Depends(caller_dependency)) -> JSONResponse:
    """Create, update or revive a connection. `secret` absent keeps the stored key, "" removes it.
    A target another connection holds (also the old target of a revived one) is 409, naming the
    target and the connection that holds it."""
    pid = admin_connection(slug, caller, name)
    if body.kind == "provider":
        return save_provider_connection(pid, name, body, caller)
    if body.provider is not None:
        raise _invalid_connection("provider: only for a connection of kind provider")
    fields = connection_fields(body)
    ciphertext = connection_store.KEEP
    if "secret" in body.model_fields_set:
        try:
            ciphertext = llm_store.encrypt(body.secret) if body.secret else None
        except llm_store.SecretsKeyError as exc:
            raise secrets_unavailable(exc) from None
    header_ciphertext = connection_store.KEEP
    before = connection_store.get(pid, name, with_deleted=True)
    adapter = adapters.get(body.kind) if body.kind not in adapters.BUILT_IN_KINDS else None
    # secret headers, and an adapter's secret fields (stored where secret headers are): encrypted, names public.
    # One protocol's secrets are never another's: a change of kind removes every stored one, and a change to
    # an adapter the key too (an adapter connection has none).
    stored = list((before or {}).get("secret_header_names") or [])
    change = dict((body.secret_settings if adapter is not None else body.secret_headers) or {})
    if before is not None and before.get("kind") != body.kind:
        change = {**{n: "" for n in stored}, **change}
        if adapter is not None:
            ciphertext = None
    # a stored key or secret header goes only where it was entered for: another origin needs them typed again
    kept_secrets = [n for n in stored if n not in change]
    if before is not None:                                # a revived one too: delete keeps its key
        if ciphertext is connection_store.KEEP:
            secret_box.kept_key(before.get("base_url"), fields["base_url"], bool(before.get("has_secret")))
        secret_box.kept_key(before.get("base_url"), fields["base_url"], bool(kept_secrets))
    names = stored
    if change:
        names, header_ciphertext = _merged_secret_headers(pid, name, change)
        if header_ciphertext is not connection_store.KEEP:
            fields["secret_header_names"] = names
    if adapter is not None:
        missing = [f.name for f in adapter.fields if f.secret and f.required and f.name not in names]
        if missing:
            raise _invalid_connection(f"secret_settings: {', '.join(missing)} required")
    if "target" in body.model_fields_set and body.target is not None:
        fields["target_key"] = checked_target(pid, name, body.target, before)
    try:
        row = connection_store.save(pid, name, fields, ciphertext=ciphertext, header_ciphertext=header_ciphertext,
                                    subject=caller.username or caller.subject)
    except errors.UniqueViolation:
        # A revive keeps its old target_key, which another connection may hold now
        key = fields.get("target_key") or (before or {}).get("target_key")
        holder = connection_store.holder_of(pid, key) if key else None
        raise HTTPException(status_code=409, detail=f"target: {key} already has a connection"
                                                    + (f", {holder}" if holder else "")) from None
    except connection_store.TargetSetOnce:
        raise target_set_once() from None               # another save set it since `before` was read
    except connection_store.ConnectionAssessed:
        raise used_connection(name) from None
    except connection_store.NameTaken:
        raise other_kind(name) from None
    retire_engine_component(pid, row, request)
    if row.get("target_key"):
        _rename_targets(pid, request)
    return JSONResponse(status_code=200, content=connection_view(_with_pid(pid, row)))


#: what a provider connection leaves out: the provider's own API decides the rest
_NOT_FOR_PROVIDER = ("method", "path", "headers", "secret_header", "body_template", "response_path", "refusal",
                     "model", "protocol_version", "secret_headers", "supports_tools", "supports_logprobs",
                     "settings", "secret_settings")


def save_provider_connection(pid: str, name: str, body: ConnectionIn, caller: Caller) -> JSONResponse:
    """A model provider's account, or a self-hosted model server (kind `provider`): its provider, its key and, for
    a self-hosted one, its address. It never reaches the assessed system; agents and test tools use it."""
    from platform_service import llm_catalogue
    from platform_service.routes.llm import clean_base_url, clean_key

    entry = llm_catalogue.PROVIDERS.get(body.provider or "")
    if entry is None:
        raise _invalid_connection(f"provider: one of {', '.join(sorted(llm_catalogue.PROVIDERS))}")
    if body.target is not None:
        raise _invalid_connection("target: a provider connection never reaches the assessed system; agents and "
                                  "test tools use it")
    sent = [f for f in _NOT_FOR_PROVIDER if f in body.model_fields_set]
    if sent:
        raise _invalid_connection(f"{', '.join(sent)}: not for a provider connection")
    label = body.label.strip()
    if not 1 <= len(label) <= 120:
        raise _invalid_connection("label: 1 to 120 characters")
    base_url = clean_base_url(body.base_url)
    if base_url is not None and not entry.base_url_editable:
        raise _invalid_connection(f"base_url: {entry.label} is called at its own address; it takes none")
    if body.provider == "compatible" and base_url is None:
        raise _invalid_connection("base_url: a self-hosted model server needs its address")
    if body.provider == "ollama" and body.secret:
        raise _invalid_connection("secret: ollama takes no key")
    if base_url is not None:
        # a self-hosted server's address follows the project's network rule, as a helper's does
        from platform_service.routes.helpers import reachable
        reachable(pid, base_url, field="base_url", operator_hosts=llm_store.operator_hosts(base_url))
    ciphertext = connection_store.KEEP
    if "secret" in body.model_fields_set:
        try:
            ciphertext = llm_store.encrypt(clean_key(body.secret)) if body.secret else None
        except llm_store.SecretsKeyError as exc:
            raise secrets_unavailable(exc) from None
    before = connection_store.get(pid, name, with_deleted=True)
    if before is not None and before["kind"] != "provider":
        raise HTTPException(status_code=409, detail=f"{name} is a connection of another kind; choose another name")
    if before is not None and ciphertext is connection_store.KEEP:
        # a stored key goes only where it was entered for: another origin needs it typed again
        secret_box.kept_key(before.get("base_url") or None, base_url, bool(before.get("has_secret")))
    try:
        row = connection_store.save_provider(pid, name, label=label, provider=body.provider, ciphertext=ciphertext,
                                             base_url=base_url, subject=caller.username or caller.subject)
    except connection_store.NameTaken:
        raise HTTPException(status_code=409, detail=f"{name} is a connection of another kind; choose another name") from None
    return JSONResponse(status_code=200, content=connection_view(_with_pid(pid, row)))


class TargetIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    #: 'system' or 'component:<key>'
    key: StrictStr


@router.post("/projects/{slug}/connections/{name}/target")
def link_target(slug: str, name: str, body: TargetIn, request: Request,
                caller: Caller = Depends(caller_dependency)) -> JSONResponse:
    """Make a connection the endpoint of a target, nothing else of it changing: the checks of a save that
    names a target (checked_target), without sending the connection again."""
    pid = admin_connection(slug, caller, name)
    before = connection_store.get(pid, name)
    if before is None:
        raise HTTPException(status_code=404, detail=f"no connection {name!r}")
    key = checked_target(pid, name, body.key, before)
    try:
        row = connection_store.link_target(pid, name, key, subject=caller.username or caller.subject)
    except errors.UniqueViolation:
        holder = connection_store.holder_of(pid, key)       # another connection took it since the check
        raise HTTPException(status_code=409, detail=f"target: {key} already has a connection"
                                                    + (f", {holder}" if holder else "")) from None
    except connection_store.TargetSetOnce:
        raise target_set_once() from None
    except connection_store.ConnectionAssessed:
        raise used_connection(name) from None
    if row is None:
        raise HTTPException(status_code=404, detail=f"no connection {name!r}")
    _rename_targets(pid, request)
    return JSONResponse(status_code=200, content=connection_view(_with_pid(pid, row)))


def _rename_targets(pid, request: Request) -> None:
    """The target dropdown names say whether and how each target is connected: refresh them when one is
    bound or removed. An engine that doesn't answer leaves the old names until the next refresh."""
    _exists, latest = db.latest_version(str(pid))
    reason = targets.ensure_mirrors(pid, token_from_headers(request.headers) or "",
                                    latest["number"] if latest else None)
    if reason:
        logger.warning("target names of project %s not refreshed: %s", pid, reason)


@router.delete("/projects/{slug}/connections/{name}", status_code=204)
def delete_connection(slug: str, name: str, request: Request, caller: Caller = Depends(caller_dependency)) -> Response:
    """Mark it deleted. The engine's component stays, so past evaluations keep what they used."""
    pid = admin_connection(slug, caller, name)
    was = connection_store.get(pid, name)
    if not connection_store.delete(pid, name):
        raise HTTPException(status_code=404, detail=f"no connection {name!r}")
    if was and was.get("target_key"):
        _rename_targets(pid, request)
    return Response(status_code=204)


@router.post("/projects/{slug}/connections/{name}/test")
def test_connection(slug: str, name: str, body: ProbeIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """One probe, without retries, through the same client the plugins use; the result is stored. A
    connection that says it carries tools or log probabilities gets one more probe for each, and fails as
    `capability_missing` when one fails."""
    from aisc_plugin_interface import connections as client

    pid = admin_connection(slug, caller, name, "connection.test")
    row = connection_store.descriptor(pid, name)
    if row is None or row["deleted_at"] is not None:
        raise HTTPException(status_code=404, detail=f"no connection {name!r}")
    try:
        descriptor = call_descriptor_of(row, pid)
    except llm_store.SecretsKeyError as exc:
        raise secrets_unavailable(exc) from None
    except llm_store.KeyUnreadable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    try:
        if descriptor.kind in adapters.BUILT_IN_KINDS:
            answer = client.call(descriptor, body.input, waits=(), **connection_allowlist.rule(pid))
        else:
            from platform_service.routes.facade import call_adapter
            answer = call_adapter(pid, descriptor, adapters.get(descriptor.kind), body.input)
    except client.EndpointError as exc:
        if _reached_by_ping(descriptor, body.input, exc):
            detail = (f"reached, key accepted: it answered {exc.status} to 'ping', since it takes a JSON request."
                      " Type one in the box to see an answer.")
            connection_store.record_test(pid, name, True, detail, result="reachable")
            return {"ok": True, "refused": False, "reachable_only": True, "status": exc.status, "detail": detail}
        error = next((code for cls, code in _PROBE_ERRORS if type(exc).__name__ == cls), "error")
        message = connection_facade.scrub(str(exc), secret_values(descriptor))
        connection_store.record_test(pid, name, False, message, result=error)
        return {"ok": False, "error": error, "detail": message}
    # a system that echoes its credentials: the answer and the refusal lose them before they are shown or stored
    answer = connection_facade.scrub_answer(answer, secret_values(descriptor))
    if answer.refused:
        connection_store.record_test(pid, name, True, f"refused: {answer.refusal_reason}", result="refused")
        return {"ok": True, "refused": True, "refusal_reason": answer.refusal_reason, "status": answer.status,
                "latency_ms": answer.latency_ms}
    if isinstance(answer.text, (dict, list)):
        recorded = json.dumps(answer.text)[:2000]
        out = {"ok": True, "refused": False, "answer": answer.text, "status": answer.status,
               "latency_ms": answer.latency_ms}
    else:
        recorded = str(answer.text)
        out = {"ok": True, "refused": False, "answer": recorded[:500], "status": answer.status,
               "latency_ms": answer.latency_ms}
    checks = _capability_checks(pid, row, descriptor) if descriptor.kind in adapters.BUILT_IN_KINDS else {}
    if checks:
        out["capabilities"] = checks
        failing = next((c for c in checks.values() if not c["ok"]), None)
        if failing:
            connection_store.record_test(pid, name, False, failing["detail"], result="capability_missing")
            return {"ok": False, "error": "capability_missing", "detail": failing["detail"], "capabilities": checks}
    connection_store.record_test(pid, name, True, recorded)
    return out


@router.get("/internal/projects/{pid}/connections/{name}")
def resolve_connection(pid: str, name: str, request: Request) -> JSONResponse:
    """A connection's descriptor without its key (`has_secret` says whether it has one), for the
    plugin-side client of an evaluation run: only the protocol doors decrypt the key, to call the system.

    Same guards as the LLM resolve route: not through the gateway (404), closed without
    PLATFORM_CONNECTIONS_TOKEN (503), the token in X-AISC-Service-Token compared in constant time
    (401). A deleted connection is 410."""
    return _internal_gate(pid, request, "connection", name) or _resolve_connection(
        pid, name, request.headers.get(run_passes.HEADER))


def _resolve_connection(pid: str, name: str, run_pass: str | None = None) -> JSONResponse:
    """resolve_connection past the gate, for a caller that has run it; a use is recorded under `run_pass`."""
    if not CONNECTION_NAME.fullmatch(name):
        return _internal(404, {"detail": f"no connection {name!r}"})
    row = connection_store.descriptor(pid, name)
    if row is None:
        return _internal(404, {"detail": f"no connection {name!r}"})
    if row["deleted_at"] is not None:
        return _internal(410, {"detail": f"connection {name!r} was deleted"})
    out = descriptor_of(row, pid)
    fingerprint = _fingerprint_of(out) if run_pass is not None else None
    # the network rule of the project, now: the run's own environment opens nothing
    out.update(connection_allowlist.rule(pid))
    _record_use(run_pass, pid, row, fingerprint)
    logger.info("connection %s of project %s resolved for a run", name, pid)
    return _internal(200, out)


@router.post("/internal/projects/{pid}/connections/{name}/run-keys")
def issue_run_key(pid: str, name: str, request: Request) -> JSONResponse:
    """A key for one evaluation run to reach one connection through the protocol endpoints; only its
    hash is stored. Guarded like the resolve route. Valid CONNECTIONS_RUN_KEY_TTL_S (12 h); under a run pass,
    no longer than the pass, and deleted when the pass is revoked."""
    return _internal_gate(pid, request, "connection", name) or _issue_run_key(
        pid, name, request.headers.get(run_passes.HEADER))
