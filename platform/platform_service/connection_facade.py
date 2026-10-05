"""The protocols a tool can reach a connection with, translated to and from AISC's own interface
(aisc_plugin_interface.connections: an input and a history in; an answer or a refusal out).

Pure functions, no I/O: app.py authenticates, calls the connection and returns what these build.
OpenAI Chat Completions (non-streaming), A2A 1.0 JSON-RPC (and the 0.3 dialect), and the Open
Inference Protocol (KServe V2) REST API.
"""
from __future__ import annotations

import time
import uuid

A2A_VERSION = "1.0"


class BadRequest(ValueError):
    """The tool's request cannot be translated; the message says why."""


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
