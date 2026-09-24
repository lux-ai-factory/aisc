"""A canonical document with one operation, from what a person can paste (spec D3)."""
from __future__ import annotations

import base64
import json
import re
from collections import Counter
from urllib.parse import parse_qsl, urlsplit

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.errors import ImportFailed

_DROP_HEADERS = {"content-type", "content-length", "host", "accept-encoding"}
_KEY_HEADERS = {"x-api-key", "api-key", "apikey"}


def infer_schema(value) -> dict:
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, int):
        return {"type": "integer"}
    if isinstance(value, float):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string"}
    if isinstance(value, list):
        return {"type": "array", "items": infer_schema(value[0]) if value else {}}
    if isinstance(value, dict):
        return {"type": "object", "properties": {k: infer_schema(v) for k, v in value.items()}}
    return {}


def _content(body: str, content_type: str) -> dict:
    if "json" in content_type:
        try:
            example = json.loads(body)
        except ValueError as exc:
            raise ImportFailed("the body says it is JSON but does not parse") from exc
        return {content_type: {"schema": infer_schema(example), "example": example}}
    if content_type == "application/x-www-form-urlencoded":
        fields = dict(parse_qsl(body, keep_blank_values=True))
        return {content_type: {"schema": {"type": "object", "properties": {k: {"type": "string"} for k in fields}},
                               "example": fields}}
    return {content_type: {"schema": {"type": "string"}, "example": body}}


def one_operation(method: str, url: str, headers: dict[str, str], body: str | None, content_type: str | None,
                  operation_id: str, summary: str = "", example_response: str | None = None) -> ImportResult:
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise ImportFailed(f"{url!r} is not an http(s) URL")
    method = method.lower()
    auth, secrets, static = None, {}, {}
    for name, value in headers.items():
        low = name.lower()
        if low == "authorization" and value.lower().startswith("bearer "):
            auth, secrets["token"] = {"scheme": "bearer"}, value[7:].strip()
        elif low == "authorization" and value.lower().startswith("basic "):
            user, _, password = base64.b64decode(value[6:].strip()).decode().partition(":")
            auth, secrets["password"] = {"scheme": "basic", "username": user}, password
        elif low in _KEY_HEADERS:
            auth, secrets["api_key"] = {"scheme": "api_key", "in": "header", "name": name}, value
        elif low == "content-type":
            content_type = content_type or value.split(";")[0].strip()
        elif low not in _DROP_HEADERS:
            static[name] = value
    op: dict = {"operationId": operation_id, "summary": summary,
                "x-aisc-binding": {"protocol": "http", "method": method, "path": parts.path or "/",
                                   "static_headers": static},
                "responses": {"200": {"description": "the answer"}}}
    query = parse_qsl(parts.query, keep_blank_values=True)
    if query:
        op["parameters"] = [{"in": "query", "name": k, "required": False, "schema": {"type": "string"}, "example": v}
                            for k, v in query]
    if body is not None:
        op["requestBody"] = {"content": _content(body, content_type or "application/json")}
    if example_response:
        try:
            parsed = json.loads(example_response)
            op["responses"]["200"]["content"] = {"application/json": {"schema": infer_schema(parsed),
                                                                      "example": parsed}}
        except ValueError:
            op["responses"]["200"]["content"] = {"text/plain": {"schema": {"type": "string"}}}
    document = {"openapi": "3.1.0", "info": {"title": parts.netloc, "version": "1"},
                "servers": [{"url": f"{parts.scheme}://{parts.netloc}"}], "paths": {parts.path or "/": {method: op}}}
    return ImportResult(document=document, auth_suggestion=auth, detected_secrets=secrets)


def synth_id(method: str, url: str) -> str:
    path = urlsplit(url).path
    return method.lower() + "_" + (re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root")


def merge(results: list[ImportResult]) -> ImportResult:
    if not results:
        raise ImportFailed("nothing to import")
    servers = Counter(r.document["servers"][0]["url"] for r in results)
    server = servers.most_common(1)[0][0]
    merged = {**results[0].document, "servers": [{"url": server}], "paths": {}}
    out = ImportResult(document=merged)
    used: set[str] = set()
    for result in results:
        if result.document["servers"][0]["url"] != server:
            out.warnings.append(f"skipped a request to {result.document['servers'][0]['url']}: "
                                f"a connector talks to one server ({server})")
            continue
        for path, item in result.document["paths"].items():
            for method, op in item.items():
                while op["operationId"] in used:
                    op["operationId"] += "_"
                used.add(op["operationId"])
                merged["paths"].setdefault(path, {})[method] = op
        out.auth_suggestion = out.auth_suggestion or result.auth_suggestion
        out.detected_secrets.update(result.detected_secrets)
        out.warnings.extend(result.warnings)
    return out
