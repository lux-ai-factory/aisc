"""Swagger 2.0 into OpenAPI 3.1: the common subset real APIs use."""
from __future__ import annotations

import copy
import json

from aisc_connectors.model import HTTP_METHODS

_SCHEMA_KEYS = ("type", "format", "items", "enum", "default", "minimum", "maximum", "pattern")


def _refs(obj):
    text = json.dumps(obj).replace("#/definitions/", "#/components/schemas/").replace(
        "#/parameters/", "#/components/parameters/")
    return json.loads(text)


def _param_schema(param: dict) -> dict:
    schema = {k: param[k] for k in _SCHEMA_KEYS if k in param}
    if schema.get("type") == "file":
        return {"type": "string", "format": "binary"}
    return schema


def _operation(op: dict, consumes: list[str], produces: list[str]) -> dict:
    out = {k: v for k, v in op.items() if k not in ("parameters", "responses", "consumes", "produces")}
    consumes = op.get("consumes") or consumes or ["application/json"]
    produces = op.get("produces") or produces or ["application/json"]
    params, form = [], {}
    for param in op.get("parameters") or []:
        where = param.get("in")
        if where == "body":
            out["requestBody"] = {"required": bool(param.get("required")),
                                  "content": {consumes[0]: {"schema": param.get("schema", {})}}}
        elif where == "formData":
            form[param["name"]] = _param_schema(param)
        else:
            params.append({k: param[k] for k in ("in", "name", "required", "description") if k in param}
                          | {"schema": _param_schema(param)})
    if form:
        media = "multipart/form-data" if "multipart/form-data" in consumes else "application/x-www-form-urlencoded"
        out["requestBody"] = {"content": {media: {"schema": {"type": "object", "properties": form}}}}
    if params:
        out["parameters"] = params
    responses = {}
    for code, response in (op.get("responses") or {}).items():
        converted = {"description": response.get("description", "")}
        if "schema" in response:
            converted["content"] = {produces[0]: {"schema": response["schema"]}}
        responses[str(code)] = converted
    out["responses"] = responses
    return out


def _security(definitions: dict) -> dict:
    schemes = {}
    for name, d in definitions.items():
        if d.get("type") == "apiKey":
            schemes[name] = {"type": "apiKey", "in": d["in"], "name": d["name"]}
        elif d.get("type") == "basic":
            schemes[name] = {"type": "http", "scheme": "basic"}
        elif d.get("type") == "oauth2" and d.get("flow") == "application":
            schemes[name] = {"type": "oauth2", "flows": {"clientCredentials": {
                "tokenUrl": d.get("tokenUrl", ""), "scopes": d.get("scopes", {})}}}
    return schemes


def convert(doc: dict) -> dict:
    doc = copy.deepcopy(doc)
    scheme = (doc.get("schemes") or ["https"])[0]
    servers = [{"url": f"{scheme}://{doc['host']}{doc.get('basePath', '')}".rstrip("/")}] if doc.get("host") else []
    paths = {}
    for path, item in (doc.get("paths") or {}).items():
        shared = item.get("parameters") or []
        paths[path] = {}
        for method in HTTP_METHODS:
            if method in item:
                op = dict(item[method])
                op["parameters"] = shared + (op.get("parameters") or [])
                paths[path][method] = _operation(op, doc.get("consumes") or [], doc.get("produces") or [])
    out = {
        "openapi": "3.1.0",
        "info": doc.get("info") or {"title": "imported", "version": "1"},
        "servers": servers,
        "paths": paths,
        "components": {
            "schemas": doc.get("definitions") or {},
            "securitySchemes": _security(doc.get("securityDefinitions") or {}),
        },
    }
    return _refs(out)
