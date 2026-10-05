"""Ready-made connectors for the LLM APIs most systems expose, with a chat mapping."""
from __future__ import annotations

from aisc_connectors.importers import ImportResult


def _doc(base_url: str, title: str, paths: dict) -> dict:
    return {"openapi": "3.1.0", "info": {"title": title, "version": "1"},
            "servers": [{"url": base_url.rstrip("/")}], "paths": paths}


def _op(op_id: str, method: str, path: str, summary: str, body_schema: dict | None = None) -> dict:
    op = {"operationId": op_id, "summary": summary, "responses": {"200": {"description": "ok"}},
          "x-aisc-binding": {"protocol": "http", "method": method, "path": path, "static_headers": {}}}
    if body_schema:
        op["requestBody"] = {"content": {"application/json": {"schema": body_schema}}}
    return op


_MESSAGES = {"type": "object", "properties": {"model": {"type": "string"}, "messages": {"type": "array", "items": {
    "type": "object", "properties": {"role": {"type": "string"}, "content": {"type": "string"}}}}}}


def openai(base_url: str, model: str = "") -> ImportResult:
    doc = _doc(base_url, "OpenAI-compatible", {
        "/chat/completions": {"post": _op("chat_completions", "post", "/chat/completions", "Chat", _MESSAGES)},
        "/models": {"get": _op("list_models", "get", "/models", "Models")},
    })
    return ImportResult(document=doc, auth_suggestion={"scheme": "bearer"}, chat_suggestion={
        "operation_id": "chat_completions", "input_mode": "messages", "input_field": "messages",
        "answer_path": "choices[0].message.content", "extra_body": {"model": model}})


def ollama(base_url: str, model: str = "") -> ImportResult:
    doc = _doc(base_url, "Ollama", {"/api/chat": {"post": _op("chat", "post", "/api/chat", "Chat", _MESSAGES)}})
    return ImportResult(document=doc, chat_suggestion={
        "operation_id": "chat", "input_mode": "messages", "input_field": "messages",
        "answer_path": "message.content", "extra_body": {"model": model, "stream": False}})


def huggingface(model_url: str) -> ImportResult:
    schema = {"type": "object", "properties": {"inputs": {"type": "string"}}}
    doc = _doc(model_url, "Hugging Face Inference", {"/": {"post": _op("infer", "post", "/", "Inference", schema)}})
    return ImportResult(document=doc, auth_suggestion={"scheme": "bearer"}, chat_suggestion={
        "operation_id": "infer", "input_mode": "text", "input_field": "inputs",
        "answer_path": "[0].generated_text", "extra_body": {}})
