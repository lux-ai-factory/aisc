"""The protocol endpoints in front of a connection, and the run keys that open them.

Four doors (AISC's own aisc/ask, OpenAI Chat Completions, A2A, the Open Inference Protocol) translate with
connection_facade and call the system with the plugins' own client. aisc/ask takes an input, a full
OpenAI-style history and params (template values, or an OpenAI-compatible model's settings, tools among
them when the connection carries tools) and answers the output, a refusal or the tool calls; a request
the platform will not send is a 400 with the reason, a failed call a 502 {error, status, detail} with
every key scrubbed. The OpenAI door carries tools and tool results the same way. A run key is accepted
only while live and, when issued under a run's pass, while that pass is; it counts a use for each ask whose
body every door reads the same way (_open_request), never for a probe. Calls run in the facade's own
threads, capped across the platform and per run (_in_facade_threads)."""
from __future__ import annotations

import json
import logging
import os
from typing import NamedTuple

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from platform_service import (adapters, connection_allowlist, connection_facade, connection_store, db, llm_store,
                              run_passes)
from platform_service.projects import looks_like_pid
from platform_service.routes.admission import _internal
from platform_service.routes.connections import (CONNECTION_NAME, RUN_KEY_PREFIX, _key_hash, adapter_connection_of,
                                                 call_descriptor_of, secret_values)

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
    adapter: object = None        # the adapter of a connection of an adapter's kind (None: built-in, or not installed)
    key_hash: str = ""            # the run key's stored hash, to count its uses on


def _facade_open(pid: str, name: str, request: Request):
    """(Opened, None) for a live key of this connection, or (None, (status, message)). It counts no use:
    a probe opens a door with it alone, an ask through _open_request."""
    if "x-forwarded-for" in request.headers or "x-forwarded-host" in request.headers:
        return None, (404, "not here")
    if not looks_like_pid(pid) or not CONNECTION_NAME.fullmatch(name):
        return None, (404, "no such connection")
    scheme, _, key = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not key.startswith(RUN_KEY_PREFIX) or db.get_project(pid) is None:
        return None, (401, "a run key is needed")
    with connection_store.connect(pid) as conn:          # one connection to the project's database
        run_key = connection_store.live_run_key(pid, name, _key_hash(key.strip()), conn=conn)
        if run_key is None:
            return None, (401, "a run key is needed")
        # a key issued under a run's pass ends with it: revoked (its row deleted then), expired, or gone
        if run_key["pass_hash"] is not None and not run_passes.is_live(run_key["pass_hash"]):
            return None, (401, "the run's pass has ended")
        row = connection_store.descriptor(pid, name, conn=conn)
    if row is None or row["deleted_at"] is not None:
        return None, (410, f"connection {name!r} was deleted")
    try:
        descriptor = call_descriptor_of(row, pid)
    except (llm_store.SecretsKeyError, llm_store.KeyUnreadable) as exc:
        return None, (503, str(exc))
    run_id = f"pass:{run_key['pass_hash']}" if run_key["pass_hash"] else f"key:{run_key['key_hash']}"
    adapter = adapters.get(row["kind"]) if row["kind"] not in adapters.BUILT_IN_KINDS else None
    return Opened(descriptor, run_id, bool(row.get("supports_tools")), secret_values(descriptor), adapter,
                  run_key["key_hash"]), None


def _facade_call(pid, opened: Opened, input, history=None, params=None, deadline=None):
    """(answer, None), or (None, the client's error) when the call failed. The key and the secret header
    values are never in either: the answer is scrubbed of every form of them (scrub_answer).
    It blocks on the system under test: the async facade routes run it in its own threads
    (_in_facade_threads) and _facade_open in the shared pool, so a slow system never stalls other requests."""
    from aisc_plugin_interface import connections as client
    try:
        if opened.descriptor.kind in adapters.BUILT_IN_KINDS:
            answer = client.call(opened.descriptor, input, history, params=params, **connection_allowlist.rule(pid))
        else:
            answer = call_adapter(pid, opened.descriptor, opened.adapter, input, history, params, deadline)
        return connection_facade.scrub_answer(answer, opened.secrets), None
    except client.EndpointError as exc:
        # a warning: the plugin sees only the answer's detail, and INFO lines don't reach the stack's log;
        # a system can echo the key, so the text is scrubbed like the answer's
        logger.warning("connection %s of project %s failed behind a protocol endpoint (%s): %s",
                       opened.descriptor.name, pid, connection_facade.error_code(exc),
                       connection_facade.scrub(str(exc), opened.secrets)[:300])
        return None, exc


def call_adapter(pid, descriptor, adapter, input, history=None, params=None, deadline=None):
    """A call to a connection of an adapter's kind, through its adapter, its network reach ending at `deadline`
    (time.monotonic(); default: the connection's own timeout from now)."""
    import time

    from aisc_plugin_interface import connections as client

    if adapter is None:
        raise client.EndpointError(f"{descriptor.label}: the {descriptor.kind} adapter is not installed")
    return adapters.call(adapter, adapter_connection_of(descriptor), input, history or [], params or {},
                         deadline=deadline if deadline is not None else time.monotonic() + descriptor.timeout_s,
                         **connection_allowlist.rule(pid))


def _history_refused(opened: Opened, history) -> JSONResponse | None:
    """A 400 when the connection's adapter takes no history and one was sent."""
    if history and opened.adapter is not None and "history" not in opened.adapter.capabilities:
        return _internal(400, {"detail": "this connection does not take a history (its adapter carries text only)"})
    return None


#: the facade calls' own threads: a call blocks up to 3 x its timeout + 4 s on the system under
#: test, and in the pool every sync route shares (anyio's default, 40 threads) enough of them stalled every
#: other request, Caddy's forward_auth to /authz/witness among them. Two caps: PLATFORM_FACADE_THREADS calls
#: at once across the platform, PLATFORM_FACADE_RUN_CAP at once per run (its pass, or a key issued without
#: one), so one run's dataset cannot take every thread from another run. A call over a cap waits (its
#: wait counts against the client's facade timeout); nothing is refused for capacity. An adapter call abandoned
#: on its timeout (abandon_on_cancel in _ask) gives its slots back at once while its thread runs on, so threads
#: still busy with abandoned adapter calls are outside both caps.
FACADE_THREADS_DEFAULT = 32
FACADE_RUN_CAP_DEFAULT = 8
_FACADE_LIMITER = None
_RUN_LIMITERS: dict[str, list] = {}      # run id -> [its anyio.CapacityLimiter, calls using it]


def _setting(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name) or default)
    except ValueError:
        return default
    return value if value >= 1 else default


def facade_threads() -> int:
    return _setting("PLATFORM_FACADE_THREADS", FACADE_THREADS_DEFAULT)


def facade_run_cap() -> int:
    return min(_setting("PLATFORM_FACADE_RUN_CAP", FACADE_RUN_CAP_DEFAULT), facade_threads())


def _facade_limiter():
    global _FACADE_LIMITER
    if _FACADE_LIMITER is None:
        import anyio

        _FACADE_LIMITER = anyio.CapacityLimiter(facade_threads())
    return _FACADE_LIMITER


async def _in_facade_threads(run_id: str, func, *args, abandon_on_cancel: bool = False, **kwargs):
    """func(*args, **kwargs) in the facade's threads: first a slot of the run (waited for without holding a
    thread), then one of the pool. The run's limiter goes when its last call ends. `abandon_on_cancel`: a
    cancelled wait returns at once and leaves the thread to finish on its own, and both slots are given back
    at once too, so that thread no longer counts against either cap."""
    import functools

    import anyio
    import anyio.to_thread

    entry = _RUN_LIMITERS.get(run_id)
    if entry is None:
        entry = _RUN_LIMITERS[run_id] = [anyio.CapacityLimiter(facade_run_cap()), 0]
    entry[1] += 1
    try:
        async with entry[0]:
            return await anyio.to_thread.run_sync(functools.partial(func, *args, **kwargs),
                                                  limiter=_facade_limiter(), abandon_on_cancel=abandon_on_cancel)
    finally:
        entry[1] -= 1
        if entry[1] == 0 and _RUN_LIMITERS.get(run_id) is entry:
            del _RUN_LIMITERS[run_id]


async def _ask(pid, opened: Opened, input, history=None, params=None):
    """(answer, None) or (None, error) of one call, the way every door makes it. A connection of an adapter's
    kind waits for one of the adapter's slots without holding a thread, and gets its answer within the
    caller's own wait (facade_timeout_s) or a timeout: an adapter that hangs never keeps a door open."""
    if opened.descriptor.kind in adapters.BUILT_IN_KINDS:
        return await _in_facade_threads(opened.run_id, _facade_call, pid, opened, input, history, params)
    import contextlib
    import time

    import anyio
    from aisc_plugin_interface import connections as client

    seconds = client.facade_timeout_s(opened.descriptor)
    deadline = time.monotonic() + seconds
    slots = adapters.limiter(opened.adapter) if opened.adapter is not None else None
    try:
        with anyio.fail_after(seconds):
            async with slots if slots is not None else contextlib.nullcontext():
                return await _in_facade_threads(opened.run_id, _facade_call, pid, opened, input, history, params,
                                                deadline=deadline, abandon_on_cancel=True)
    except TimeoutError:
        exc = client.EndpointTimeout(f"{opened.descriptor.label}: no answer within {seconds}s")
        logger.warning("connection %s of project %s failed behind a protocol endpoint (timeout): %s",
                       opened.descriptor.name, pid, exc)
        return None, exc


async def _capped_body(request: Request) -> bytes | None:
    """The body, or None when it is more than MAX_ASK_BYTES: read no further than that."""
    cap = connection_facade.MAX_ASK_BYTES
    try:
        if int(request.headers.get("content-length") or 0) > cap:
            return None
    except ValueError:
        pass
    raw = bytearray()
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > cap:
            return None
    return bytes(raw)


async def _open_request(pid: str, name: str, request: Request):
    """What every ask's door does first: (Opened, its body, None), or (None, None, (status, message)) for a
    key it does not accept or a body over MAX_ASK_BYTES. The body is the JSON object sent, None when it
    is not one, for the door to refuse in its own words. Only an ask with a JSON object counts a use."""
    opened, err = await run_in_threadpool(_facade_open, pid, name, request)
    if err:
        return None, None, err
    raw = await _capped_body(request)
    if raw is None:
        return None, None, (413, f"the request is more than {connection_facade.MAX_ASK_BYTES} bytes")
    try:
        body = json.loads(raw)
    except ValueError:
        body = None
    if not isinstance(body, dict):
        return opened, None, None
    await run_in_threadpool(connection_store.count_run_key_use, pid, name, opened.key_hash)
    return opened, body, None


@router.post("/internal/facade/{pid}/{name}/aisc/ask")
async def facade_aisc_ask(pid: str, name: str, request: Request) -> JSONResponse:
    """AISC's own door: {input, history?, params?} in; the answer, a refusal or tool calls out. A request
    the platform will not send is 400 with the reason; a failed call is 502 {error, status, detail}."""
    opened, body, err = await _open_request(pid, name, request)
    if err:
        return _internal(err[0], {"detail": err[1]})
    try:
        input, history, params = connection_facade.ask_request(body, opened.descriptor.kind, opened.supports_tools)
    except connection_facade.BadRequest as exc:
        return _internal(400, {"detail": str(exc)})
    refused = _history_refused(opened, history)
    if refused:
        return refused
    answer, failed = await _ask(pid, opened, input, history or None, params)
    if failed:
        status, out = connection_facade.ask_failure(failed, opened.secrets)
        return _internal(status, out)
    return _internal(200, connection_facade.ask_answer(answer))


@router.post("/internal/facade/{pid}/{name}/openai/v1/chat/completions")
async def facade_openai_chat(pid: str, name: str, request: Request) -> JSONResponse:
    opened, body, err = await _open_request(pid, name, request)
    if err:
        kind = "authentication_error" if err[0] == 401 else "invalid_request_error"
        return _internal(err[0], connection_facade.openai_error(err[1], kind))
    try:
        input, history, params = connection_facade.openai_to_core(body or {}, opened.descriptor.kind,
                                                                  opened.supports_tools)
    except connection_facade.BadRequest as exc:
        return _internal(400, connection_facade.openai_error(str(exc)))
    if _history_refused(opened, history):
        return _internal(400, connection_facade.openai_error("this connection does not take a history"))
    answer, failed = await _ask(pid, opened, input, history or None, params)
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
    opened, body, err = await _open_request(pid, name, request)
    if err:
        return _internal(err[0], {"detail": err[1]})
    if body is None:
        return _internal(200, connection_facade.jsonrpc_error(None, -32700, "parse error"))
    rid = body.get("id")
    try:
        dialect, input = connection_facade.a2a_to_core(body)
    except KeyError:
        return _internal(200, connection_facade.jsonrpc_error(rid, -32601, f"method not found: {body.get('method')}"))
    except connection_facade.BadRequest as exc:
        return _internal(200, connection_facade.jsonrpc_error(rid, -32602, str(exc)))
    answer, failed = await _ask(pid, opened, input)
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
    if model != name:       # a wrong path, refused before the key is checked like a malformed pid or name
        return _internal(404, {"error": f"no model {model!r}; this endpoint serves {name!r}"})
    opened, body, err = await _open_request(pid, name, request)
    if err:
        return _internal(err[0], {"error": err[1]})
    try:
        inputs = connection_facade.oip_to_core(body or {})
    except connection_facade.BadRequest as exc:
        return _internal(400, {"error": str(exc)})
    answers = []
    for item in inputs:
        answer, failed = await _ask(pid, opened, item)
        if failed:
            return _internal(502, {"error": f"the system under test failed: {connection_facade.error_code(failed)}"})
        answers.append(answer)
    return _internal(200, connection_facade.core_to_oip(name, (body or {}).get("id"), answers))
