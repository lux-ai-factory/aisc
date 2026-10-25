"""The protocol endpoints in front of a connection, and the run keys that open them."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from platform_service import connection_allowlist, connection_facade, connection_store, db, llm_store
from platform_service.projects import looks_like_pid
from platform_service.routes.admission import _internal
from platform_service.routes.connections import _PROBE_ERRORS, CONNECTION_NAME, RUN_KEY_PREFIX, _key_hash, call_descriptor_of

router = APIRouter()

logger = logging.getLogger(__name__)


# A run gets a key for one connection and the URLs of four doors to it: AISC's own (input and
# history in, answer or refusal out), OpenAI Chat Completions, A2A and the Open Inference Protocol.
# The doors translate (connection_facade) and call the connection with the same client the plugins
# use; inside the network only, like the resolve route.

def _facade_open(pid: str, name: str, request: Request):
    """(descriptor, None) for a live key of this connection, or (None, (status, message))."""
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return None, (404, "not here")
    if not looks_like_pid(pid) or not CONNECTION_NAME.match(name):
        return None, (404, "no such connection")
    scheme, _, key = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not key.startswith(RUN_KEY_PREFIX) or db.get_project(pid) is None:
        return None, (401, "a run key is needed")
    if not connection_store.use_run_key(pid, name, _key_hash(key.strip())):
        return None, (401, "a run key is needed")
    row = connection_store.descriptor(pid, name)
    if row is None or row["deleted_at"] is not None:
        return None, (410, f"connection {name!r} was deleted")
    try:
        return call_descriptor_of(row, pid), None
    except (llm_store.SecretsKeyError, llm_store.KeyUnreadable) as exc:
        return None, (503, str(exc))


def _facade_call(pid, descriptor, input, history=None):
    """(answer, None), or (None, error code) when the connection failed. The key is never in it.
    It blocks on the system under test: the async facade routes run it in its own threads
    (_in_facade_threads) and _facade_open in the shared pool, so a slow system never stalls other requests."""
    from aisc_plugin_interface import connections as client
    try:
        return client.call(descriptor, input, history, **connection_allowlist.rule(pid)), None
    except client.EndpointError as exc:
        code = next((c for cls, c in _PROBE_ERRORS if type(exc).__name__ == cls), "error")
        # a warning: the plugin sees only a 502, and INFO lines don't reach the stack's log. The client's
        # messages never hold the key.
        logger.warning("connection %s of project %s failed behind a protocol endpoint (%s): %s",
                       descriptor.name, pid, code, str(exc)[:300])
        return None, code


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


@router.post("/internal/facade/{pid}/{name}/aisc/ask")
async def facade_aisc_ask(pid: str, name: str, request: Request) -> JSONResponse:
    descriptor, err = await run_in_threadpool(_facade_open, pid, name, request)
    if err:
        return _internal(err[0], {"detail": err[1]})
    body = await _json_body(request)
    if body is None or "input" not in body or not isinstance(body.get("history", []), list):
        return _internal(400, {"detail": "{input, history?: [{role, content}]}"})
    answer, failed = await _in_facade_threads(_facade_call, pid, descriptor, body["input"], body.get("history") or None)
    if failed:
        return _internal(502, {"error": failed})
    return _internal(200, {"output": answer.text, "refused": answer.refused, "refusal_reason": answer.refusal_reason,
                           "status": answer.status, "latency_ms": answer.latency_ms})


@router.post("/internal/facade/{pid}/{name}/openai/v1/chat/completions")
async def facade_openai_chat(pid: str, name: str, request: Request) -> JSONResponse:
    descriptor, err = await run_in_threadpool(_facade_open, pid, name, request)
    if err:
        kind = "authentication_error" if err[0] == 401 else "invalid_request_error"
        return _internal(err[0], connection_facade.openai_error(err[1], kind))
    body = await _json_body(request)
    try:
        input, history = connection_facade.openai_to_core(body or {})
    except connection_facade.BadRequest as exc:
        return _internal(400, connection_facade.openai_error(str(exc)))
    answer, failed = await _in_facade_threads(_facade_call, pid, descriptor, input, history or None)
    if failed:
        return _internal(502, connection_facade.openai_error(f"the system under test failed: {failed}", "api_error", failed))
    return _internal(200, connection_facade.core_to_openai(name, answer))


@router.get("/internal/facade/{pid}/{name}/openai/v1/models")
def facade_openai_models(pid: str, name: str, request: Request) -> JSONResponse:
    _, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], connection_facade.openai_error(err[1], "authentication_error"))
    return _internal(200, connection_facade.openai_models(name))


@router.get("/internal/facade/{pid}/{name}/a2a/.well-known/agent-card.json")
def facade_a2a_card(pid: str, name: str, request: Request) -> JSONResponse:
    descriptor, err = _facade_open(pid, name, request)
    if err:
        return _internal(err[0], {"detail": err[1]})
    root = os.environ.get("PLATFORM_INTERNAL_URL", "http://platform:8000").rstrip("/")
    return _internal(200, connection_facade.a2a_card(descriptor.label or name, f"{root}/internal/facade/{pid}/{name}/a2a"))


@router.post("/internal/facade/{pid}/{name}/a2a")
async def facade_a2a_rpc(pid: str, name: str, request: Request) -> JSONResponse:
    descriptor, err = await run_in_threadpool(_facade_open, pid, name, request)
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
    answer, failed = await _in_facade_threads(_facade_call, pid, descriptor, input)
    if failed:
        return _internal(200, connection_facade.jsonrpc_error(rid, -32603, f"the system under test failed: {failed}"))
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
    descriptor, err = await run_in_threadpool(_facade_open, pid, name, request)
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
        answer, failed = await _in_facade_threads(_facade_call, pid, descriptor, item)
        if failed:
            return _internal(502, {"error": f"the system under test failed: {failed}"})
        answers.append(answer)
    return _internal(200, connection_facade.core_to_oip(name, (body or {}).get("id"), answers))
