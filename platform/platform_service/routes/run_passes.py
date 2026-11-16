"""The internal routes' gate, the passes the worker takes for a plugin run (/internal/run-passes), and the run
keys issued under them."""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import uuid

from aisc_identity.service_tokens import HEADER as SERVICE_TOKEN_HEADER, ServiceRefused, identify
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
import psycopg

from platform_service import (adapters, connection_facade, connection_store, db, run_passes)
from platform_service.projects import looks_like_pid
from platform_service.connections import CONNECTION_NAME, _fingerprint_of, _target_of, descriptor_of
from platform_service.routes.admission import _internal

router = APIRouter()

logger = logging.getLogger(__name__)


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
    hands it to the plugin in place of that token. ``ttl_s``, when sent, is how long it lasts: as long as the
    worker's test may run, never longer than CONNECTIONS_RUN_KEY_TTL_S."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    try:
        identify(request.headers.get(SERVICE_TOKEN_HEADER), {"worker": "PLATFORM_CONNECTIONS_TOKEN"})
    except ServiceRefused as refused:
        return _internal(refused.status, {"detail": refused.detail})
    body = body if isinstance(body, dict) else {}
    ttl_s = body.get("ttl_s")
    if ttl_s is not None:
        longest = int(os.environ.get("CONNECTIONS_RUN_KEY_TTL_S") or 12 * 3600)
        # bool is an int to Python, and a pass of True seconds is no lifetime the worker meant
        if not isinstance(ttl_s, int) or isinstance(ttl_s, bool) or not 60 <= ttl_s <= longest:
            return _internal(422, {"detail": f"ttl_s: whole seconds from 60 to {longest}"})
    try:
        run_pass, expires = run_passes.mint(body.get("refs"), evaluation_plugin=body.get("evaluation_plugin"),
                                            project=body.get("project"), ttl_s=ttl_s)
    except run_passes.Refused as refused:
        return _internal(refused.status, {"detail": refused.detail})
    return _internal(201, {"pass": run_pass, "expires_at": expires.isoformat()})


def _uuid_or_none(value: str | None) -> str | None:
    try:
        return str(uuid.UUID(value)) if value else None
    except ValueError:
        return None


@router.delete("/internal/run-passes")
def revoke_run_pass(request: Request) -> Response:
    """The worker ends a run's pass when the run ends, and with it the run keys issued under it in every
    project it named; an unknown or already ended pass is no error. The run's call trace is sealed in the
    ledger with it (run_passes.revoke), citing X-AISC-Request-Id and X-AISC-Run-Id when the worker sends them."""
    if _behind_gateway(request):
        return _internal(404, {"detail": "not here"})
    run_pass = request.headers.get(run_passes.HEADER) or ""
    # the run's request and id, which its trace's seal cites (an id that is not a uuid is left out)
    request_id, run_id = (_uuid_or_none(request.headers.get(h)) for h in ("X-AISC-Request-Id", "X-AISC-Run-Id"))
    for pid in run_passes.revoke(run_pass, request_id=request_id, run_id=run_id):
        # the keys issued under it; one left by a database that fails here is refused at use anyway
        try:
            connection_store.revoke_run_keys(pid, run_passes.hash_of(run_pass))
        except psycopg.Error as exc:
            logger.warning("run keys of project %s for an ended pass not deleted: %s", pid, exc)
    return Response(status_code=204)


def _record_use(run_pass: str | None, pid: str, row: dict, fingerprint: str) -> None:
    """A run reached this connection under its pass (run_passes.record); the key never goes in."""
    if run_pass is not None:
        run_passes.record(run_pass, pid, row["name"], row["kind"], fingerprint)


RUN_KEY_PREFIX = "aisc-run-"


def _key_hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


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
                           "capabilities": connection_facade.capabilities(
                               row["kind"], bool(row.get("supports_tools")),
                               adapters.get(row["kind"]) if row["kind"] not in adapters.BUILT_IN_KINDS else None),
                           "target": _target_of(pid, row), "endpoints": {
        "aisc": {"ask_url": f"{root}/aisc/ask"},
        "openai": {"base_url": f"{root}/openai/v1", "model": name},
        "a2a": {"agent_card_url": f"{root}/a2a/.well-known/agent-card.json", "rpc_url": f"{root}/a2a"},
        "oip": {"base_url": f"{root}/oip", "model": name}}})
