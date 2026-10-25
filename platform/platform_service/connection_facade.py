"""The protocols a tool can reach a connection with, translated to and from AISC's own interface
(aisc_plugin_interface.connections: an input, a history and params in; an answer or a refusal out).

Pure functions, no I/O: routes/facade.py authenticates, calls the connection and returns what these build.
AISC's own door (aisc/ask: `{input, history?, params?}`; the history is OpenAI chat messages, checked by
the interface's check_history; params fill a template's {{params.x}} or, for an OpenAI-compatible
connection, are the model's generation settings from OPENAI_PARAMS), OpenAI Chat Completions
(non-streaming), A2A 1.0 JSON-RPC (and the 0.3 dialect), and the Open Inference Protocol (KServe V2)
REST API. A request the platform will not send is a BadRequest (a 400); what the system did is a 502
whose detail is the client's message with every key scrubbed (ask_failure).

It imports only the standard library and aisc_plugin_interface: the integrator's trial gateway loads this
file by its path, so the trial and the platform translate with the same code.
"""
from __future__ import annotations

import json
import re
import time
import uuid

A2A_VERSION = "1.0"


class BadRequest(ValueError):
    """The tool's request cannot be translated; the message says why."""


# What a request may carry
#: the generation settings an OpenAI-compatible connection takes from a caller; the rest of the request
#: (model, messages, stream, n, logprobs, ...) is the platform's to build
OPENAI_PARAMS = ("temperature", "top_p", "max_tokens", "max_completion_tokens", "stop", "seed",
                 "presence_penalty", "frequency_penalty", "logit_bias", "response_format", "user",
                 "tools", "tool_choice", "parallel_tool_calls")
TOOL_PARAMS = ("tools", "tool_choice", "parallel_tool_calls")
MAX_PARAMS = 64
MAX_TOOLS = 128
PARAM_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ERROR_CODES = (("BlockedAddress", "blocked"), ("EndpointAuthError", "auth"), ("EndpointNotFound", "not_found"),
               ("EndpointTimeout", "timeout"), ("EndpointBadResponse", "bad_response"))
ASK_SHAPE = "{input, history?: [messages], params?: {}}"
MAX_ASK_BYTES = 2_097_152


def _check_tools(params: dict) -> None:
    tools = params.get("tools")
    if "tools" in params:
        if not isinstance(tools, list) or not tools:
            raise BadRequest("params: tools is a list of functions")
        if len(tools) > MAX_TOOLS:
            raise BadRequest(f"params: {len(tools)} tools, more than {MAX_TOOLS}")
        for i, tool in enumerate(tools):
            function = tool.get("function") if isinstance(tool, dict) else None
            if (not isinstance(tool, dict) or tool.get("type") != "function" or not isinstance(function, dict)
                    or not isinstance(function.get("name"), str) or not _TOOL_NAME.match(function["name"])):
                raise BadRequest(f"params: tools[{i}] needs type 'function' and a function with a name (letters,"
                                 " digits, _ and -, up to 64)")
            if "parameters" in function and not isinstance(function["parameters"], dict):
                raise BadRequest(f"params: tools[{i}].function.parameters is a JSON schema object")
    if "tool_choice" in params:
        choice = params["tool_choice"]
        named = (isinstance(choice, dict) and choice.get("type") == "function"
                 and isinstance(choice.get("function"), dict) and isinstance(choice["function"].get("name"), str))
        if choice not in ("none", "auto", "required") and not named:
            raise BadRequest("params: tool_choice is none, auto, required or {type: function, function: {name}}")
    if "parallel_tool_calls" in params and not isinstance(params["parallel_tool_calls"], bool):
        raise BadRequest("params: parallel_tool_calls is true or false")


def check_params(kind: str, supports_tools: bool, params: dict) -> dict:
    """A copy of `params` when this connection can be sent them; BadRequest naming the first fault."""
    from aisc_plugin_interface.connections import MAX_PARAMS_BYTES

    try:
        size = len(json.dumps(params).encode())
    except (TypeError, ValueError) as exc:
        raise BadRequest(f"params: not JSON: {str(exc)[:100]}") from None
    if size > MAX_PARAMS_BYTES:
        raise BadRequest(f"params: {size} bytes as JSON, more than {MAX_PARAMS_BYTES}")
    if len(params) > MAX_PARAMS:
        raise BadRequest(f"params: {len(params)} parameters, more than {MAX_PARAMS}")
    for key in params:
        if not isinstance(key, str) or not PARAM_NAME.match(key):
            raise BadRequest(f"params: {key!r} is not a parameter name")
    if any(k in params for k in TOOL_PARAMS):
        if kind != "openai":
            raise BadRequest(f"params: a {kind} connection does not carry tools; only an OpenAI-compatible one does")
        if not supports_tools:
            raise BadRequest("params: this connection does not carry tools (it carries text, history)")
        _check_tools(params)
    if kind == "openai":
        for key in params:
            if key not in OPENAI_PARAMS:
                raise BadRequest(f"params: {key!r} is not a parameter an OpenAI-compatible connection takes"
                                 f" ({', '.join(OPENAI_PARAMS)})")
    return dict(params)


# AISC's own door
def ask_request(body, kind: str, supports_tools: bool) -> tuple[object, list, dict]:
    """(input, history, params) of an aisc/ask body, every check made; BadRequest otherwise."""
    from aisc_plugin_interface import connections as client

    if not isinstance(body, dict) or "input" not in body:
        raise BadRequest(ASK_SHAPE)
    try:
        history = client.check_history(body.get("history"))
    except client.BadRequest as exc:
        raise BadRequest(str(exc)) from None
    params = body.get("params")
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise BadRequest("params: an object of parameters")
    return body["input"], history, check_params(kind, supports_tools, params)


def ask_answer(answer) -> dict:
    """aisc/ask's 200 body."""
    return {"output": answer.text, "refused": answer.refused, "refusal_reason": answer.refusal_reason,
            "status": answer.status, "latency_ms": answer.latency_ms,
            "tool_calls": getattr(answer, "tool_calls", None) or None}


def error_code(exc) -> str:
    """The short code of a client error, by its exact class: blocked, auth, not_found, timeout,
    bad_response, or error."""
    return next((code for cls, code in ERROR_CODES if type(exc).__name__ == cls), "error")


def scrub(text: str, secrets: list) -> str:
    """`text` with each secret value replaced by ***, the longest first; empty values skipped."""
    for value in sorted((v for v in secrets or [] if v), key=len, reverse=True):
        text = text.replace(value, "***")
    return text


def ask_failure(exc, secrets: list) -> tuple[int, dict]:
    """(status, body) of a failed call: 400 for a request the interface will not send, else 502 with the
    error's code, the system's status and the message, scrubbed then cut to 300 characters."""
    detail = scrub(str(exc), secrets)[:300]
    if type(exc).__name__ == "BadRequest":
        return 400, {"detail": detail}
    status = getattr(exc, "status", None)
    status = status if isinstance(status, int) and not isinstance(status, bool) else None
    return 502, {"error": error_code(exc), "status": status, "detail": detail}


# OpenAI-compatible
def openai_to_core(body: dict) -> tuple[str, list]:
    """(input, history) from a chat.completions request: the last user message is the input, the ones
    before it the history."""
    if body.get("stream"):
        raise BadRequest("streaming is not supported; send stream: false")
    messages = body.get("messages")
    if not isinstance(messages, list) or not messages:
        raise BadRequest("messages is required")
    for m in messages:
        if not isinstance(m, dict) or m.get("role") not in ("system", "user", "assistant") or not isinstance(m.get("content"), str):
            raise BadRequest("each message needs a role (system, user or assistant) and text content")
    if messages[-1]["role"] != "user":
        raise BadRequest("the last message must be the user's")
    return messages[-1]["content"], [{"role": m["role"], "content": m["content"]} for m in messages[:-1]]


def core_to_openai(model: str, answer) -> dict:
    if answer.refused:
        reason = answer.refusal_reason or ""
        message = {"role": "assistant", "content": f"Refused: {reason}" if reason else "Refused", "refusal": reason}
        finish = "content_filter"
    else:
        text = answer.text if isinstance(answer.text, str) else _json_text(answer.text)
        message, finish = {"role": "assistant", "content": text, "refusal": None}, "stop"
    return {"id": "chatcmpl-" + uuid.uuid4().hex, "object": "chat.completion", "created": int(time.time()),
            "model": model, "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


def openai_error(message: str, kind: str = "invalid_request_error", code: str | None = None) -> dict:
    return {"error": {"message": message, "type": kind, "param": None, "code": code}}


def openai_models(model: str) -> dict:
    return {"object": "list", "data": [{"id": model, "object": "model", "created": 0, "owned_by": "aisc"}]}


# A2A
def a2a_card(label: str, rpc_url: str) -> dict:
    return {
        "name": label,
        "description": f"{label}, an AI system under assessment, reached through the AI Assessment Sandbox Configurator.",
        "supportedInterfaces": [{"url": rpc_url, "protocolBinding": "JSONRPC", "protocolVersion": A2A_VERSION}],
        "version": "1.0.0",
        "capabilities": {"streaming": False, "pushNotifications": False, "extendedAgentCard": False},
        "securitySchemes": {"bearer": {"httpAuthSecurityScheme": {"scheme": "Bearer"}}},
        "securityRequirements": [{"schemes": {"bearer": {"list": []}}}],
        "defaultInputModes": ["text/plain", "application/json"],
        "defaultOutputModes": ["text/plain", "application/json"],
        "skills": [{"id": "ask", "name": "Answer", "description": f"Answers a question the way {label} does.",
                    "tags": ["assessment", "system-under-test"]}],
    }


def a2a_to_core(request: dict) -> tuple[str, object]:
    """(dialect, input) from a JSON-RPC request; dialect "1.0" or "0.3". Raises KeyError for an unknown
    method and BadRequest for bad params."""
    method = request.get("method")
    if method not in ("SendMessage", "message/send"):
        raise KeyError(method)
    dialect = "1.0" if method == "SendMessage" else "0.3"
    message = (request.get("params") or {}).get("message")
    if not isinstance(message, dict) or not isinstance(message.get("parts"), list) or not message["parts"]:
        raise BadRequest("params.message with parts is required")
    texts = [p["text"] for p in message["parts"] if isinstance(p, dict) and isinstance(p.get("text"), str)]
    if texts:
        return dialect, "".join(texts)
    data = [p["data"] for p in message["parts"] if isinstance(p, dict) and "data" in p]
    if data:
        return dialect, data[0]
    raise BadRequest("the message has no text or data part")


def _a2a_part(value, dialect: str) -> dict:
    if isinstance(value, str):
        return {"text": value} if dialect == "1.0" else {"kind": "text", "text": value}
    return {"data": value} if dialect == "1.0" else {"kind": "data", "data": value}


def core_to_a2a(dialect: str, answer) -> dict:
    """The JSON-RPC result: an agent message, or a rejected task for a refusal."""
    if not answer.refused:
        if dialect == "1.0":
            return {"message": {"messageId": uuid.uuid4().hex, "role": "ROLE_AGENT", "parts": [_a2a_part(answer.text, dialect)]}}
        return {"kind": "message", "messageId": uuid.uuid4().hex, "role": "agent", "parts": [_a2a_part(answer.text, dialect)]}
    reason = answer.refusal_reason or ""
    if dialect == "1.0":
        return {"task": {"id": uuid.uuid4().hex, "status": {"state": "TASK_STATE_REJECTED", "message": {
            "messageId": uuid.uuid4().hex, "role": "ROLE_AGENT", "parts": [{"text": reason}]}}}}
    return {"kind": "task", "id": uuid.uuid4().hex, "status": {"state": "rejected", "message": {
        "kind": "message", "messageId": uuid.uuid4().hex, "role": "agent", "parts": [{"kind": "text", "text": reason}]}}}


def jsonrpc_result(rid, result) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def jsonrpc_error(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


# Open Inference Protocol
def oip_server() -> dict:
    return {"name": "aisc-connection", "version": "1", "extensions": []}


def oip_model(name: str) -> dict:
    return {"name": name, "versions": [], "platform": "aisc-connection",
            "inputs": [{"name": "input", "datatype": "BYTES", "shape": [-1]}],
            "outputs": [{"name": "output", "datatype": "BYTES", "shape": [-1]},
                        {"name": "refused", "datatype": "BOOL", "shape": [-1]}]}


def oip_to_core(body: dict) -> list:
    """The inputs to ask one by one: each element of a BYTES tensor named "input"; or, for feature
    tensors, one structured input {tensor name: data}."""
    inputs = body.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise BadRequest("inputs is required")
    for t in inputs:
        if not isinstance(t, dict) or not isinstance(t.get("name"), str) or not isinstance(t.get("data"), list):
            raise BadRequest("each input needs a name and data")
    text = next((t for t in inputs if t["name"] == "input" and t.get("datatype") == "BYTES"), None)
    if text is not None:
        return [str(x) for x in text["data"]]
    return [{t["name"]: t["data"] for t in inputs}]


def core_to_oip(name: str, rid, answers: list) -> dict:
    outputs = [a.refusal_reason or "" if a.refused else (a.text if isinstance(a.text, str) else _json_text(a.text))
               for a in answers]
    out = {"model_name": name, "outputs": [
        {"name": "output", "shape": [len(outputs)], "datatype": "BYTES", "data": outputs},
        {"name": "refused", "shape": [len(outputs)], "datatype": "BOOL", "data": [bool(a.refused) for a in answers]}]}
    if rid is not None:
        out["id"] = rid
    return out


def _json_text(value) -> str:
    import json
    return json.dumps(value)
