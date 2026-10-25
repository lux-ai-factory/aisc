"""The protocol endpoints in front of a connection, and the run keys that open them."""
from __future__ import annotations

import logging
import os
from typing import NamedTuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from platform_service import connection_allowlist, connection_facade, connection_store, db, llm_store, run_passes
from platform_service.projects import looks_like_pid
from platform_service.routes.admission import _internal
from platform_service.routes.connections import (CONNECTION_NAME, RUN_KEY_PREFIX, _key_hash, call_descriptor_of,
                                                 secret_values)

router = APIRouter()

logger = logging.getLogger(__name__)


# A run gets a key for one connection and the URLs of four doors to it: AISC's own (input and
# history in, answer or refusal out), OpenAI Chat Completions, A2A and the Open Inference Protocol.
# The doors translate (connection_facade) and call the connection with the same client the plugins
# use; inside the network only, like the resolve route.

class Opened(NamedTuple):
    """A door opened with a live run key: what to call the system with, and what to scrub from errors."""
    descriptor: object            # aisc_plugin_interface.connections.Descriptor, the key decrypted
    run_id: str                   # "pass:<pass_hash>", or "key:<key_hash>" for a key issued without a pass
    supports_tools: bool          # the connection carries tools (an OpenAI-compatible one only)
    secrets: list                 # the values never to answer back (secret_values)


def _facade_open(pid: str, name: str, request: Request):
    """(Opened, None) for a live key of this connection, or (None, (status, message))."""
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return None, (404, "not here")
    if not looks_like_pid(pid) or not CONNECTION_NAME.match(name):
        return None, (404, "no such connection")
    scheme, _, key = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not key.startswith(RUN_KEY_PREFIX) or db.get_project(pid) is None:
        return None, (401, "a run key is needed")
    run_key = connection_store.live_run_key(pid, name, _key_hash(key.strip()))
    if run_key is None:
        return None, (401, "a run key is needed")
    # a key issued under a run's pass ends with it: revoked (its row deleted then), expired, or gone
    if run_key["pass_hash"] is not None and not run_passes.is_live(run_key["pass_hash"]):
        return None, (401, "the run's pass has ended")
    connection_store.count_run_key_use(pid, name, run_key["key_hash"])
    row = connection_store.descriptor(pid, name)
    if row is None or row["deleted_at"] is not None:
        return None, (410, f"connection {name!r} was deleted")
    try:
        descriptor = call_descriptor_of(row, pid)
    except (llm_store.SecretsKeyError, llm_store.KeyUnreadable) as exc:
        return None, (503, str(exc))
    run_id = f"pass:{run_key['pass_hash']}" if run_key["pass_hash"] else f"key:{run_key['key_hash']}"
    return Opened(descriptor, run_id, bool(row.get("supports_tools")), secret_values(descriptor)), None


def _facade_call(pid, opened: Opened, input, history=None, params=None):
    """(answer, None), or (None, the client's error) when the call failed. The key is never in it.
    It blocks on the system under test: the async facade routes run it in its own threads
    (_in_facade_threads) and _facade_open in the shared pool, so a slow system never stalls other requests."""
    from aisc_plugin_interface import connections as client
    try:
        return client.call(opened.descriptor, input, history, params=params, **connection_allowlist.rule(pid)), None
    except client.EndpointError as exc:
        # a warning: the plugin sees only the answer's detail, and INFO lines don't reach the stack's log;
        # a system can echo the key, so the text is scrubbed like the answer's
        logger.warning("connection %s of project %s failed behind a protocol endpoint (%s): %s",
                       opened.descriptor.name, pid, connection_facade.error_code(exc),
                       connection_facade.scrub(str(exc), opened.secrets)[:300])
        return None, exc


#: the facade calls' own threads: a call blocks up to 3 x its timeout + 4 s on the system under
#: test, and in the pool every sync route shares (anyio's default, 40 threads) enough of them stalled every
#: other request, Caddy's forward_auth to /authz/witness among them. A call over the cap waits for a slot.
FACADE_THREADS_DEFAULT = 16
_FACADE_LIMITER = None


def _facade_limiter():
    global _FACADE_LIMITER
    if _FACADE_LIMITER is None:
        import anyio

        try:
            size = int(os.environ.get("PLATFORM_FACADE_THREADS") or FACADE_THREADS_DEFAULT)
        except ValueError:
            size = FACADE_THREADS_DEFAULT
        _FACADE_LIMITER = anyio.CapacityLimiter(max(1, size))
    return _FACADE_LIMITER


async def _in_facade_threads(func, *args):
    import functools

    import anyio.to_thread

    return await anyio.to_thread.run_sync(functools.partial(func, *args), limiter=_facade_limiter())


async def _json_body(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


async def _ask_body(request: Request):
    """The parsed body, or the answer refusing it: 413 over MAX_ASK_BYTES, 400 for no JSON."""
    too_big = _internal(413, {"detail": f"the request is more than {connection_facade.MAX_ASK_BYTES} bytes"})
    try:
        if int(request.headers.get("content-length") or 0) > connection_facade.MAX_ASK_BYTES:
            return None, too_big
    except ValueError:
        pass
    raw = await request.body()
    if len(raw) > connection_facade.MAX_ASK_BYTES:
        return None, too_big
    try:
        import json
        return json.loads(raw), None
    except ValueError:
        return None, _internal(400, {"detail": connection_facade.ASK_SHAPE})


@router.post("/internal/facade/{pid}/{name}/aisc/ask")
async def facade_aisc_ask(pid: str, name: str, request: Request) -> JSONResponse:
    """AISC's own door: {input, history?, params?} in; the answer, a refusal or tool calls out. A request
    the platform will not send is 400 with the reason; a failed call is 502 {error, status, detail}."""
    opened, err = await run_in_threadpool(_facade_open, pid, name, request)
    if err:
        return _internal(err[0], {"detail": err[1]})
    body, refused = await _ask_body(request)
    if refused:
        return refused
    try:
        input, history, params = connection_facade.ask_request(body, opened.descriptor.kind, opened.supports_tools)
    except connection_facade.BadRequest as exc:
        return _internal(400, {"detail": str(exc)})
    answer, failed = await _in_facade_threads(_facade_call, pid, opened, input, history or None, params)
    if failed:
        status, out = connection_facade.ask_failure(failed, opened.secrets)
        return _internal(status, out)
    return _internal(200, connection_facade.ask_answer(answer))


@router.post("/internal/facade/{pid}/{name}/openai/v1/chat/completions")
async def facade_openai_chat(pid: str, name: str, request: Request) -> JSONResponse:
    opened, err = await run_in_threadpool(_facade_open, pid, name, request)
    if err:
        kind = "authentication_error" if err[0] == 401 else "invalid_request_error"
        return _internal(err[0], connection_facade.openai_error(err[1], kind))
    body = await _json_body(request)
    try:
        input, history = connection_facade.openai_to_core(body or {})
    except connection_facade.BadRequest as exc:
        return _internal(400, connection_facade.openai_error(str(exc)))
    answer, failed = await _in_facade_threads(_facade_call, pid, opened, input, history or None)
    if failed:
        status, out = connection_facade.ask_failure(failed, opened.secrets)
        if status == 400:
            return _internal(400, connection_facade.openai_error(out["detail"]))
        code = out["error"]
        return _internal(502, connection_facade.openai_error(f"the system under test failed: {code}", "api_error", code))
    return _internal(200, connection_facade.core_to_openai(name, answer))


@router.get("/internal/facade/{pid}/{name}/openai/v1/models")
def facade_openai_models(pid: str, name: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], connection_facade.openai_error(err[1], "authentication_error"))
    return _internal(200, connection_facade.openai_models(name))


@router.get("/internal/facade/{pid}/{name}/a2a/.well-known/agent-card.json")
def facade_a2a_card(pid: str, name: str, request: Request) -> JSONResponse:
    opened, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"detail": err[1]})
    root = os.environ.get("PLATFORM_INTERNAL_URL", "http://platform:8000").rstrip("/")
    return _internal(200, connection_facade.a2a_card(opened.descriptor.label or name, f"{root}/internal/facade/{pid}/{name}/a2a"))


@router.post("/internal/facade/{pid}/{name}/a2a")
async def facade_a2a_rpc(pid: str, name: str, request: Request) -> JSONResponse:
    opened, err = await run_in_threadpool(_facade_open, pid, name, request)
    if err:
        return _internal(err[0], {"detail": err[1]})
    body = await _json_body(request)
    if body is None:
        return _internal(200, connection_facade.jsonrpc_error(None, -32700, "parse error"))
    rid = body.get("id")
    try:
        dialect, input = connection_facade.a2a_to_core(body)
    except KeyError:
        return _internal(200, connection_facade.jsonrpc_error(rid, -32601, f"method not found: {body.get('method')}"))
    except connection_facade.BadRequest as exc:
        return _internal(200, connection_facade.jsonrpc_error(rid, -32602, str(exc)))
    answer, failed = await _in_facade_threads(_facade_call, pid, opened, input)
    if failed:
        return _internal(200, connection_facade.jsonrpc_error(
            rid, -32603, f"the system under test failed: {connection_facade.error_code(failed)}"))
    return _internal(200, connection_facade.jsonrpc_result(rid, connection_facade.core_to_a2a(dialect, answer)))


@router.get("/internal/facade/{pid}/{name}/oip/v2")
def facade_oip_server(pid: str, name: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    return _internal(err[0], {"error": err[1]}) if err else _internal(200, connection_facade.oip_server())


@router.get("/internal/facade/{pid}/{name}/oip/v2/health/{which}")
def facade_oip_health(pid: str, name: str, which: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"error": err[1]})
    return _internal(200, {}) if which in ("live", "ready") else _internal(404, {"error": "not found"})


@router.get("/internal/facade/{pid}/{name}/oip/v2/models/{model}")
def facade_oip_model(pid: str, name: str, model: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"error": err[1]})
    if model != name:
        return _internal(404, {"error": f"no model {model!r}; this endpoint serves {name!r}"})
    return _internal(200, connection_facade.oip_model(name))


@router.get("/internal/facade/{pid}/{name}/oip/v2/models/{model}/ready")
def facade_oip_model_ready(pid: str, name: str, model: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"error": err[1]})
    return _internal(200, {}) if model == name else _internal(404, {"error": f"no model {model!r}"})


@router.post("/internal/facade/{pid}/{name}/oip/v2/models/{model}/infer")
async def facade_oip_infer(pid: str, name: str, model: str, request: Request) -> JSONResponse:
    opened, err = await run_in_threadpool(_facade_open, pid, name, request)
    if err:
        return _internal(err[0], {"error": err[1]})
    if model != name:
        return _internal(404, {"error": f"no model {model!r}; this endpoint serves {name!r}"})
    body = await _json_body(request)
    try:
        inputs = connection_facade.oip_to_core(body or {})
    except connection_facade.BadRequest as exc:
        return _internal(400, {"error": str(exc)})
    answers = []
    for item in inputs:
        answer, failed = await _in_facade_threads(_facade_call, pid, opened, item)
        if failed:
            return _internal(502, {"error": f"the system under test failed: {connection_facade.error_code(failed)}"})
        answers.append(answer)
    return _internal(200, connection_facade.core_to_oip(name, (body or {}).get("id"), answers))
