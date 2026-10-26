"""Manage → Connections, the assessment targets, and each project's allowed internal hosts."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
from urllib.parse import urlsplit

from aisc_identity import Caller
from aisc_identity.fastapi import caller_dependency
from aisc_identity.headers import token_from_headers
from aisc_identity.service_tokens import HEADER as SERVICE_TOKEN_HEADER, ServiceRefused, identify
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
import psycopg
from psycopg import errors
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from platform_service import (connection_allowlist, connection_facade, connection_store, db, llm_store, run_passes,
                              target_store, targets)
from platform_service.projects import looks_like_pid
from platform_service.routes.admission import _internal, admin_project, no_project, role_or_404, secrets_unavailable

router = APIRouter()

logger = logging.getLogger(__name__)


# The systems a project assesses over the network. An admin registers, tests and deletes them;
# the engine sees each as a `resource` component `connection:<pid>/<name>`; the plugin-side
# client (aisc_plugin_interface.connections) resolves one on the internal route below.

CONNECTION_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key"}
#: a plain header with a name like these is refused: its value would be stored and shown in the clear
_CREDENTIAL_LIKE = re.compile(r"(?i)(token|secret|passw|api[-_]?key|auth|session|cookie|signature|credential)")
MAX_SECRET_HEADERS = 20
MASK = "***"


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: StrictStr
    kind: StrictStr
    base_url: StrictStr
    method: StrictStr = "POST"
    path: StrictStr = ""
    headers: dict[str, StrictStr] = {}
    secret_header: StrictStr | None = None
    body_template: object | None = None
    response_path: StrictStr | None = None
    refusal: dict | None = None
    model: StrictStr | None = None
    timeout_s: int = 60
    protocol_version: StrictStr | None = None
    secret: StrictStr | None = None
    #: credentials in headers of the connection's own choosing, write-only like `secret`: absent keeps the
    #: stored set, {name: value} sets that header, {name: ""} removes it, names not mentioned are kept
    secret_headers: dict[str, StrictStr] | None = None
    #: an OpenAI-compatible connection's function calling and log probabilities (a PUT without them: false)
    supports_tools: StrictBool = False
    supports_logprobs: StrictBool = False
    #: the assessment target this is the endpoint of ('system' or 'component:<key>'); set once
    target: StrictStr | None = None


class ProbeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # text for a chat system, or a JSON object for a structured one (a scorer takes an applicant)
    input: StrictStr | dict = "ping"


def _invalid_connection(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def connection_fields(body: ConnectionIn) -> dict:
    """The columns to store, after every check; nothing is written when one fails."""
    label = body.label.strip()
    if not 1 <= len(label) <= 120:
        raise _invalid_connection("label: 1 to 120 characters")
    if body.kind not in ("openai", "rest", "a2a", "oip"):
        raise _invalid_connection("kind: openai, rest, a2a or oip")
    parts = urlsplit(body.base_url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _invalid_connection("base_url: an http(s) URL with a host")
    method = body.method.upper()
    if method not in ("GET", "POST", "PUT"):
        raise _invalid_connection("method: GET, POST or PUT")
    for name, value in body.headers.items():
        if not _HEADER_NAME.fullmatch(name):
            raise _invalid_connection(f"headers: {name!r} is not a header name")
        if "\r" in value or "\n" in value:
            raise _invalid_connection(f"headers: {name}: a header value on one line")
        if name.lower() in _SECRET_HEADERS:
            raise _invalid_connection(f"headers: {name} carries a credential; put it in secret_header")
        if _CREDENTIAL_LIKE.search(name):
            raise _invalid_connection(f"headers: {name} looks like a credential; mark it secret (secret_headers)")
    if body.secret_header is not None:
        if "\r" in body.secret_header or "\n" in body.secret_header:
            raise _invalid_connection("secret_header: 'Name: ...{{secret}}...' on one line")
        name, sep, value = body.secret_header.partition(":")
        if not sep or not _HEADER_NAME.fullmatch(name.strip()) or "{{secret}}" not in value:
            raise _invalid_connection("secret_header: 'Name: ...{{secret}}...'")
    plain = {h.lower() for h in body.headers}
    key_header = body.secret_header.partition(":")[0].strip().lower() if body.secret_header else None
    for name, value in (body.secret_headers or {}).items():
        if not _HEADER_NAME.fullmatch(name):
            raise _invalid_connection(f"secret_headers: {name!r} is not a header name")
        if "\r" in value or "\n" in value or len(value) > 4096:
            raise _invalid_connection(f"secret_headers: {name}: a header value on one line, up to 4096 characters")
        if name.lower() in plain:
            raise _invalid_connection(f"secret_headers: {name} is also a plain header")
        if name.lower() == key_header:
            raise _invalid_connection(f"secret_headers: {name} is where the key goes (secret_header)")
    if not 1 <= body.timeout_s <= 600:
        raise _invalid_connection("timeout_s: 1 to 600")
    if body.refusal is not None:
        status = body.refusal.get("status")
        if (not isinstance(status, list) or not status
                or not all(isinstance(x, int) and 100 <= x <= 599 for x in status)
                or not isinstance(body.refusal.get("path", ""), str)
                or not isinstance(body.refusal.get("match", {}), dict)
                or set(body.refusal) - {"status", "path", "match"}):
            raise _invalid_connection("refusal: {status: [codes], path?: str, match?: {path: value}}")
    if body.kind == "rest":
        if not (body.response_path or "").strip():
            raise _invalid_connection("response_path: where the answer is in the response")
        if body.body_template is None and method != "GET":
            raise _invalid_connection("body_template: the request body, with {{input}}")
    if body.kind in ("openai", "oip") and not (body.model or "").strip():
        raise _invalid_connection("model: the model the endpoint serves")
    if body.protocol_version is not None and (body.kind != "a2a" or body.protocol_version not in ("1.0", "0.3")):
        raise _invalid_connection("protocol_version: 1.0 or 0.3, for an a2a connection")
    if body.supports_tools and body.kind != "openai":
        raise _invalid_connection("supports_tools: only an OpenAI-compatible connection carries tools")
    if body.supports_logprobs and body.kind != "openai":
        raise _invalid_connection("supports_logprobs: only an OpenAI-compatible connection carries log probabilities")
    return {"label": label, "kind": body.kind, "base_url": body.base_url.strip().rstrip("/"), "method": method,
            "path": body.path.strip(), "headers": dict(body.headers), "secret_header": body.secret_header,
            "body_template": body.body_template, "response_path": body.response_path,
            "refusal": body.refusal, "model": body.model, "timeout_s": body.timeout_s,
            "protocol_version": body.protocol_version, "supports_tools": body.supports_tools,
            "supports_logprobs": body.supports_logprobs}


def connection_view(row: dict) -> dict:
    out = {k: row.get(k) for k in connection_store.PUBLIC}
    for k in ("updated_at", "last_test_at"):
        out[k] = row[k].isoformat() if row.get(k) else None
    out["engine_component"] = str(row["engine_component"]) if row.get("engine_component") else None
    out["has_secret"] = bool(row.get("has_secret"))
    out["secret_headers"] = list(out.pop("secret_header_names", None) or [])
    target = target_store.get(row["pid"], row["target_key"]) if row.get("target_key") and row.get("pid") else None
    out["target"] = {"key": target["key"], "kind": target["kind"], "label": target["label"]} if target else None
    out.pop("target_key", None)
    return out


def admin_connection(slug: str, caller: Caller, name: str) -> str:
    pid = admin_project(slug, caller)["pid"]
    if not CONNECTION_NAME.fullmatch(name):
        raise HTTPException(status_code=422, detail="name: lower-case letters, digits and hyphens, up to 63")
    return pid


LEGACY_MIRROR = "Legacy connection: {label}, pick its target instead"


def retire_engine_component(pid: str, row: dict, request: Request) -> None:
    """A connection made before targets had an engine component of its own; evaluations now pick
    the target's instead (O1). The old one is kept, for the evaluations that used it, and renamed
    so the evaluation form says what to pick instead."""
    if row.get("engine_component") is None:
        return
    from platform_service import engine_components
    try:
        engine_components.rename(pid, token_from_headers(request.headers) or "", str(row["engine_component"]),
                                 LEGACY_MIRROR.format(label=row["label"]))
    except engine_components.EngineUnavailable as exc:
        logger.warning("legacy engine component of connection %s (project %s) not renamed: %s",
                       row["name"], pid, exc)


def _with_pid(pid: str, row: dict | None) -> dict | None:
    return {**row, "pid": pid} if row else row


@router.get("/projects/{slug}/connections")
def list_connections(slug: str, caller: Caller = Depends(caller_dependency)) -> dict:
    pid = admin_project(slug, caller)["pid"]
    return {"connections": [connection_view(_with_pid(pid, r)) for r in connection_store.list_connections(pid)]}


def target_set_once() -> HTTPException:
    return HTTPException(status_code=422, detail="target: what a connection reaches is set once; create a new "
                                                 "connection to reach another one")


@router.put("/projects/{slug}/connections/{name}")
def save_connection(slug: str, name: str, body: ConnectionIn, request: Request,
                    caller: Caller = Depends(caller_dependency)) -> JSONResponse:
    """Create, update or revive a connection. `secret` absent keeps the stored key, "" removes it.
    A target another connection holds (also the old target of a revived one) is 409, naming the
    target and the connection that holds it."""
    pid = admin_connection(slug, caller, name)
    fields = connection_fields(body)
    ciphertext = connection_store.KEEP
    if "secret" in body.model_fields_set:
        try:
            ciphertext = llm_store.encrypt(body.secret) if body.secret else None
        except llm_store.SecretsKeyError as exc:
            raise secrets_unavailable(exc) from None
    header_ciphertext = connection_store.KEEP
    if body.secret_headers:
        names, header_ciphertext = _merged_secret_headers(pid, name, body.secret_headers)
        if header_ciphertext is not connection_store.KEEP:
            fields["secret_header_names"] = names
    before = connection_store.get(pid, name, with_deleted=True)
    if "target" in body.model_fields_set and body.target is not None:
        if not targets.is_key(body.target) or target_store.get(pid, body.target) is None:
            raise HTTPException(status_code=422, detail=f"target: {body.target!r} is not the system or a component of this project")
        if before and before.get("target_key") and before["target_key"] != body.target:
            raise target_set_once()
        holder = connection_store.holder_of(pid, body.target)
        if holder is not None and holder != name:
            raise HTTPException(status_code=409, detail=f"target: {body.target} already has a connection, {holder}")
        fields["target_key"] = body.target
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
    retire_engine_component(pid, row, request)
    if row.get("target_key"):
        _rename_targets(pid, request)
    return JSONResponse(status_code=200, content=connection_view(_with_pid(pid, row)))


def _stored_secret_headers(row: dict | None) -> dict[str, str]:
    """The decrypted secret headers of a stored connection; {} without any."""
    token = (row or {}).get("secret_headers_ciphertext")
    return json.loads(llm_store.decrypt((row or {}).get("name") or "", token)) if token else {}


def _merged_secret_headers(pid: str, name: str, change: dict[str, str]):
    """(names, ciphertext) of the stored set with `change` applied ("" removes a name), or (names, KEEP)
    when nothing changes. 503 without the secrets key, 409 for a stored set no key decrypts, 422 over
    MAX_SECRET_HEADERS."""
    try:
        values = _stored_secret_headers(connection_store.descriptor(pid, name))
        merged = dict(values)
        for header, value in change.items():
            if value:
                merged[header] = value
            else:
                merged.pop(header, None)
        if len(merged) > MAX_SECRET_HEADERS:
            raise _invalid_connection(f"secret_headers: up to {MAX_SECRET_HEADERS}")
        if merged == values:
            return sorted(values), connection_store.KEEP
        return sorted(merged), (llm_store.encrypt(json.dumps(merged, sort_keys=True)) if merged else None)
    except llm_store.SecretsKeyError as exc:
        raise secrets_unavailable(exc) from None
    except llm_store.KeyUnreadable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


def _rename_targets(pid, request: Request) -> None:
    """The target dropdown names say whether and how each target is connected: refresh them when one is
    bound or removed. An engine that doesn't answer leaves the old names until the next refresh."""
    _exists, latest = db.latest_version(str(pid))
    reason = targets.ensure_mirrors(pid, token_from_headers(request.headers) or "",
                                    latest["number"] if latest else None)
    if reason:
        logger.warning("target names of project %s not refreshed: %s", pid, reason)


@router.post("/projects/{slug}/connections/{name}/link")
def link_connection(slug: str, name: str, request: Request, caller: Caller = Depends(caller_dependency)) -> JSONResponse:
    """Connections are no engine components any more (targets plan v2, O1): an older one's is
    renamed legacy, kept for the evaluations that used it; evaluations pick the target."""
    pid = admin_connection(slug, caller, name)
    row = connection_store.get(pid, name)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no connection {name!r}")
    retire_engine_component(pid, row, request)
    connection_store.record_link(pid, name, retired=row.get("engine_component") is not None)
    return JSONResponse(status_code=200, content=connection_view(_with_pid(pid, row)))


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


def descriptor_of(row: dict, pid: str | None = None) -> dict:
    """What anyone the internal routes let in may see of a connection: every setting, whether it has a key
    (`has_secret`), never the key itself, and the target it is the endpoint of (part of what the
    connection is, so of its fingerprint). Nothing is decrypted here."""
    out = {k: row.get(k) for k in connection_store.PUBLIC if k not in ("engine_component", "last_test_at",
                                                                       "last_test_ok", "last_test_detail",
                                                                       "target_key")}
    out["updated_at"] = row["updated_at"].isoformat() if row.get("updated_at") else None
    # the secret headers by name, their values masked: the fingerprint and the client's copy hold none
    out["headers"] = {**(out.get("headers") or {}), **{h: MASK for h in out.pop("secret_header_names", None) or []}}
    out["has_secret"] = row.get("secret_ciphertext") is not None
    out["target"] = _target_of(pid, row) if pid else None
    return out


def call_descriptor_of(row: dict, pid: str | None = None):
    """The plugin-interface Descriptor to call the system with, the key decrypted: the one place a key is
    read back, for the protocol doors and the Test button. Raises llm_store.SecretsKeyError or
    llm_store.KeyUnreadable."""
    from aisc_plugin_interface import connections as client

    out = descriptor_of(row, pid)
    out["secret"] = llm_store.decrypt(row["name"], row["secret_ciphertext"]) if row.get("secret_ciphertext") else None
    secret_headers = _stored_secret_headers(row)
    out["headers"] = {**out["headers"], **secret_headers}
    descriptor = client.Descriptor.from_dict(out)
    descriptor.secret_header_names = sorted(secret_headers)       # for secret_values
    return descriptor


def secret_values(descriptor) -> list[str]:
    """The values to scrub from any error text of a call with this descriptor: its key and the values of
    its secret headers."""
    headers = descriptor.headers or {}
    values = [descriptor.secret] + [headers.get(h) for h in getattr(descriptor, "secret_header_names", [])]
    return [v for v in values if v]


_PROBE_ERRORS = connection_facade.ERROR_CODES


def _reached_by_ping(descriptor, sent, exc) -> bool:
    """A `ping` checks that the system is reached and takes the key. A chat answers it; a system whose whole
    request body is the input (a scorer) answers a 4xx, since "ping" is not a request it understands: that
    answer comes from the system itself, after the key was accepted. 401, 403 and 404 are still failures."""
    whole_body = descriptor.kind == "rest" and isinstance(descriptor.body_template, str) \
        and descriptor.body_template.strip() == "{{input}}"
    status = getattr(exc, "status", None)
    return sent == "ping" and whole_body and status is not None and 400 <= status < 500 \
        and status not in (401, 403, 404)


@router.post("/projects/{slug}/connections/{name}/test")
def test_connection(slug: str, name: str, body: ProbeIn, caller: Caller = Depends(caller_dependency)) -> dict:
    """One probe, without retries, through the same client the plugins use; the result is stored. A
    connection that says it carries tools or log probabilities gets one more probe for each, and fails as
    `capability_missing` when one fails."""
    from aisc_plugin_interface import connections as client

    pid = admin_connection(slug, caller, name)
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
        answer = client.call(descriptor, body.input, waits=(), **connection_allowlist.rule(pid))
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
    checks = _capability_checks(pid, row, descriptor)
    if checks:
        out["capabilities"] = checks
        failing = next((c for c in checks.values() if not c["ok"]), None)
        if failing:
            connection_store.record_test(pid, name, False, failing["detail"], result="capability_missing")
            return {"ok": False, "error": "capability_missing", "detail": failing["detail"], "capabilities": checks}
    connection_store.record_test(pid, name, True, recorded)
    return out


#: the function the Test button asks a connection that carries tools to call
PROBE_TOOL = {"type": "function", "function": {"name": "aisc_probe", "description": "Answers that the endpoint calls tools.",
                                               "parameters": {"type": "object", "properties": {}}}}


def _capability_checks(pid: str, row: dict, descriptor) -> dict:
    """One more probe per capability the connection says it has, tools before logprobs: {name: {ok, detail}};
    {} without any."""
    from aisc_plugin_interface import connections as client

    checks = {}
    secrets = secret_values(descriptor)
    if row.get("supports_tools"):
        try:
            answer = client.call(descriptor, "Call the function aisc_probe.", None, params={
                "tools": [PROBE_TOOL], "tool_choice": {"type": "function", "function": {"name": "aisc_probe"}}},
                waits=(), **connection_allowlist.rule(pid))
            called = any(isinstance(c, dict) and (c.get("function") or {}).get("name") == "aisc_probe"
                         for c in answer.tool_calls or [])
            checks["tools"] = {"ok": True, "detail": "called aisc_probe"} if called else {
                "ok": False, "detail": "tools: the endpoint answered without calling the function it was asked to call"}
        except client.EndpointError as exc:
            checks["tools"] = {"ok": False, "detail": f"tools: {connection_facade.error_code(exc)}: "
                                                      f"{connection_facade.scrub(str(exc), secrets)}"}
    if row.get("supports_logprobs"):
        try:
            client.call(descriptor, "ping", None, params={"logprobs": True, "top_logprobs": 1}, waits=(),
                        **connection_allowlist.rule(pid))
            checks["logprobs"] = {"ok": True,
                                  "detail": "the endpoint accepted logprobs: true; the log probabilities are not read"}
        except client.EndpointError as exc:
            status = getattr(exc, "status", None)
            checks["logprobs"] = {"ok": False, "detail": (
                f"logprobs: the endpoint refused logprobs: true ({status})" if status is not None else
                f"logprobs: {connection_facade.error_code(exc)}: {connection_facade.scrub(str(exc), secrets)}")}
    return checks


def _behind_gateway(request: Request) -> bool:
    return "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers


def _internal_gate(pid: str, request: Request, kind: str = "", name: str = "") -> JSONResponse | None:
    """The internal routes' guards: not through the gateway, then either a plugin run's pass that names
    this target or connection (run_passes), or the stack's connections token compared in constant time,
    and a known project."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    run_pass = request.headers.get(run_passes.HEADER)
    if run_pass is not None:
        try:
            run_passes.check(run_pass, pid, kind, name)
        except run_passes.Refused as refused:
            return _internal(refused.status, {"detail": refused.detail})
    else:
        try:
            identify(request.headers.get(SERVICE_TOKEN_HEADER), {"worker": "PLATFORM_CONNECTIONS_TOKEN"})
        except ServiceRefused as refused:
            return _internal(refused.status, {"detail": refused.detail})
    if not looks_like_pid(pid) or db.get_project(pid) is None:
        return _internal(404, {"detail": f"no project {pid!r}"})
    return None


@router.post("/internal/run-passes")
def mint_run_pass(body: dict, request: Request) -> JSONResponse:
    """A pass for one plugin run, naming the run's target and connection references, all of the run's own
    project (``project``, its platform pid); the worker asks for it with the stack's connections token and
    hands it to the plugin in place of that token."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    try:
        identify(request.headers.get(SERVICE_TOKEN_HEADER), {"worker": "PLATFORM_CONNECTIONS_TOKEN"})
    except ServiceRefused as refused:
        return _internal(refused.status, {"detail": refused.detail})
    try:
        body = body if isinstance(body, dict) else {}
        run_pass, expires = run_passes.mint(body.get("refs"), evaluation_plugin=body.get("evaluation_plugin"),
                                            project=body.get("project"))
    except run_passes.Refused as refused:
        return _internal(refused.status, {"detail": refused.detail})
    return _internal(201, {"pass": run_pass, "expires_at": expires.isoformat()})


@router.delete("/internal/run-passes")
def revoke_run_pass(request: Request) -> Response:
    """The worker ends a run's pass when the run ends, and with it the run keys issued under it in every
    project it named; an unknown or already ended pass is no error."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    run_pass = request.headers.get(run_passes.HEADER) or ""
    for pid in run_passes.revoke(run_pass):
        # the keys issued under it; one left by a database that fails here is refused at use anyway
        try:
            connection_store.revoke_run_keys(pid, run_passes.hash_of(run_pass))
        except psycopg.Error as exc:
            logger.warning("run keys of project %s for an ended pass not deleted: %s", pid, exc)
    return Response(status_code=204)


def _endpoint_of_target(pid: str, key: str) -> tuple[str | None, JSONResponse | None]:
    """The name of the connection that is this target's endpoint, or the answer why there is none."""
    target = target_store.get(pid, key) if targets.is_key(key) else None
    if target is None:
        return None, _internal(404, {"detail": f"no target {key!r}"})
    name = connection_store.holder_of(pid, key)
    if name is None:
        # reason: the one 404 a plugin may read as "skip an optional target" (plugin-interface is_no_endpoint)
        return None, _internal(404, {"detail": f"{target['label']} has no endpoint: set one under Manage,"
                                               " Components and connections", "reason": "no_endpoint"})
    return name, None


def _target_of(pid: str, row: dict) -> dict | None:
    target = target_store.get(pid, row["target_key"]) if row.get("target_key") else None
    if target is None:
        return None
    return {"key": target["key"], "kind": target["kind"], "component_kind": target["component_kind"],
            "label": target["label"], "last_card_number": target["last_card_number"]}


@router.get("/internal/projects/{pid}/targets/{key}/connection")
def resolve_target_connection(pid: str, key: str, request: Request) -> JSONResponse:
    """The endpoint of an assessment target, as resolve_connection gives a connection by name."""
    refused = _internal_gate(pid, request, "target", key)
    if refused:
        return refused
    name, missing = _endpoint_of_target(pid, key)
    return missing or _resolve_connection(pid, name, request.headers.get(run_passes.HEADER))


@router.post("/internal/projects/{pid}/targets/{key}/run-keys")
def issue_target_run_key(pid: str, key: str, request: Request) -> JSONResponse:
    """A run key for the endpoint of an assessment target."""
    refused = _internal_gate(pid, request, "target", key)
    if refused:
        return refused
    name, missing = _endpoint_of_target(pid, key)
    return missing or _issue_run_key(pid, name, request.headers.get(run_passes.HEADER))


@router.get("/internal/projects/{pid}/connections/{name}")
def resolve_connection(pid: str, name: str, request: Request) -> JSONResponse:
    """A connection's descriptor without its key (`has_secret` says whether it has one), for the
    plugin-side client of an evaluation run: only the protocol doors decrypt the key, to call the system.

    Same guards as the LLM resolve route: not through the gateway (404), closed without
    PLATFORM_CONNECTIONS_TOKEN (503), the token in X-AISC-Service-Token compared in constant time
    (401). A deleted connection is 410."""
    return _internal_gate(pid, request, "connection", name) or _resolve_connection(
        pid, name, request.headers.get(run_passes.HEADER))


def _fingerprint_of(descriptor: dict) -> str:
    """The plugin-side Descriptor fingerprint of a connection as descriptor_of gives it, what a run key
    and a recorded use both carry."""
    from aisc_plugin_interface import connections as client
    return client.Descriptor.from_dict(descriptor).fingerprint()


def _record_use(run_pass: str | None, pid: str, row: dict, fingerprint: str) -> None:
    """A run reached this connection under its pass (run_passes.record); the key never goes in."""
    if run_pass is not None:
        run_passes.record(run_pass, pid, row["name"], row["kind"], fingerprint)


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


# ── Assessment targets ────────────────────────────────────────────────────────
# What each evaluation is about: the system, or one component of its AI card. Any member reads
# them; an editor refreshes them from the card (the card's own editors add components); the
# qualification app calls the refresh after every card save. Every call to another module is made
# with the caller's own token.

def _targets_answer(pid: str, synced: dict | None = None) -> dict:
    from platform_service import db as _db

    _exists, latest = _db.latest_version(str(pid))
    number = latest["number"] if latest else None
    return {"targets": targets.view(pid, number), "latest_card": number,
            "reason": (synced or {}).get("reason")}


@router.get("/projects/{slug}/targets")
def list_targets(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    targets.ensure_system(found["pid"], found["name"])
    return _targets_answer(found["pid"])


@router.post("/projects/{slug}/targets/sync")
def sync_targets(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    role_or_404(slug, caller, "editor")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    targets.ensure_system(found["pid"], found["name"])
    synced = targets.sync(found["pid"], token_from_headers(request.headers) or "")
    return _targets_answer(found["pid"], synced)


@router.get("/projects/{slug}/targets/assessable-by")
def targets_assessable_by(slug: str, request: Request, caller: Caller = Depends(caller_dependency)) -> dict:
    """Per target, the installed tests that can assess it, from what the engine says each declares
    (asked with the caller's own token), and whether some of them call their target (so need a
    connection). An engine that does not answer lists none, and says so."""
    from platform_service import engine_components

    role_or_404(slug, caller)
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    targets.ensure_system(found["pid"], found["name"])
    rows = targets.view(found["pid"], None)
    try:
        plugins = engine_components.plugin_declarations(found["pid"], token_from_headers(request.headers) or "")
    except engine_components.EngineUnavailable as exc:
        logger.warning("installed tests of project %s not read: %s", found["pid"], exc)
        return {"assessable_by": {t["key"]: [] for t in rows}, "some_need_a_connection": False,
                "reason": "the installed tests could not be read: try again later"}
    return {"assessable_by": targets.assessable_by(rows, plugins),
            "some_need_a_connection": targets.some_need_a_connection(plugins), "reason": None}


# ── Allowed internal hosts ────────────────────────────────────────────────────
# Per project; its owners and platform admins edit it. The deployment's CONNECTIONS_ALLOWED_HOSTS
# is a floor shown read-only; the stack's own services, loopback and metadata are never allowed
# here (connection_allowlist).

class AllowedHostIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    note: StrictStr | None = None


def owner_project(slug: str, caller: Caller) -> str:
    """The project's pid, for an owner or a platform admin; a stranger gets 404, a lesser member 403."""
    role_or_404(slug, caller, "owner")
    found = db.get_project(slug)
    if found is None:
        raise no_project(slug)
    return found["pid"]


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
    pid = owner_project(slug, caller)
    return {"floor": connection_allowlist.floor(),
            "entries": [_allowed_view(r) for r in connection_allowlist.entries(pid)]}


@router.put("/projects/{slug}/allowed-hosts/{entry}")
def put_allowed_host(slug: str, entry: str, body: AllowedHostIn,
                     caller: Caller = Depends(caller_dependency)) -> dict:
    pid = owner_project(slug, caller)
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
    pid = owner_project(slug, caller)
    host = _entry_or_422(entry)
    _not_the_floor(host)
    if not connection_allowlist.remove(pid, host):
        raise HTTPException(status_code=404, detail=f"{host} is not allowed in this project")
    logger.info("project %s no longer allows %s", pid, host)
    return Response(status_code=204)


RUN_KEY_PREFIX = "aisc-run-"


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


@router.post("/internal/projects/{pid}/connections/{name}/run-keys")
def issue_run_key(pid: str, name: str, request: Request) -> JSONResponse:
    """A key for one evaluation run to reach one connection through the protocol endpoints; only its
    hash is stored. Guarded like the resolve route. Valid CONNECTIONS_RUN_KEY_TTL_S (12 h); under a run pass,
    no longer than the pass, and deleted when the pass is revoked."""
    return _internal_gate(pid, request, "connection", name) or _issue_run_key(
        pid, name, request.headers.get(run_passes.HEADER))


def _issue_run_key(pid: str, name: str, run_pass: str | None = None) -> JSONResponse:
    """issue_run_key past the gate, for a caller that has run it; a use is recorded under `run_pass`."""
    row = connection_store.descriptor(pid, name) if CONNECTION_NAME.fullmatch(name) else None
    if row is None or row["deleted_at"] is not None:
        return _internal(404, {"detail": f"no connection {name!r}"})
    fingerprint = _fingerprint_of(descriptor_of(row, pid))
    key = RUN_KEY_PREFIX + secrets.token_hex(32)
    ttl = int(os.environ.get("CONNECTIONS_RUN_KEY_TTL_S") or 12 * 3600)
    # under a pass, the key ends with it: never after it, and deleted when the worker revokes it
    pass_hash = run_passes.hash_of(run_pass) if run_pass is not None else None
    not_after = run_passes.expires_at(run_pass) if run_pass is not None else None
    expires = connection_store.issue_run_key(pid, name, _key_hash(key), fingerprint, ttl, pass_hash, not_after)
    _record_use(run_pass, pid, row, fingerprint)
    root = f"{os.environ.get('PLATFORM_INTERNAL_URL', 'http://platform:8000').rstrip('/')}/internal/facade/{pid}/{name}"
    logger.info("run key issued for connection %s of project %s", name, pid)
    # What the platform's endpoints carry: text and a history, and tools on an OpenAI-compatible connection
    # that carries them; a plugin that needs more refuses the run before it starts.
    return _internal(201, {"key": key, "expires_at": expires.isoformat(), "connection": name,
                           "capabilities": connection_facade.capabilities(row["kind"], bool(row.get("supports_tools"))),
                           "target": _target_of(pid, row), "endpoints": {
        "aisc": {"ask_url": f"{root}/aisc/ask"},
        "openai": {"base_url": f"{root}/openai/v1", "model": name},
        "a2a": {"agent_card_url": f"{root}/a2a/.well-known/agent-card.json", "rpc_url": f"{root}/a2a"},
        "oip": {"base_url": f"{root}/oip", "model": name}}})
