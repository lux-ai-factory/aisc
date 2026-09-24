"""Swagger 2.0 into OpenAPI 3.1: the common subset real APIs use."""
from __future__ import annotations

import copy

from aisc_connectors.model import HTTP_METHODS

_SCHEMA_KEYS = ("type", "format", "items", "enum", "default", "minimum", "maximum", "pattern")

_REF_PREFIXES = {
    "#/definitions/": "#/components/schemas/",
    "#/parameters/": "#/components/parameters/",
    "#/responses/": "#/components/responses/",
}


def _rewrite_ref(ref: str) -> str:
    for prefix, replacement in _REF_PREFIXES.items():
        if ref.startswith(prefix):
            return replacement + ref[len(prefix):]
    return ref


def _refs(obj):
    """Walk the document structurally, rewriting only the values of "$ref" keys.

    A string-replace over the whole dumped JSON would also rewrite ref-shaped text that
    happens to sit in an unrelated string value (a description, an example, ...).
    """
    if isinstance(obj, dict):
        return {k: (_rewrite_ref(v) if k == "$ref" and isinstance(v, str) else _refs(v))
               for k, v in obj.items()}
    if isinstance(obj, list):
        return [_refs(v) for v in obj]
    return obj


def _param_schema(param: dict) -> dict:
    schema = {k: param[k] for k in _SCHEMA_KEYS if k in param}
    if schema.get("type") == "file":
        return {"type": "string", "format": "binary"}
    return schema


def _convert_param(param: dict) -> dict:
    return {k: param[k] for k in ("in", "name", "required", "description") if k in param} | {
        "schema": _param_schema(param)}


def _merge_params(shared: list[dict], op_params: list[dict]) -> list[dict]:
    """Operation-level parameters win over path-level ones sharing the same (name, in)."""
    overridden = {(p.get("name"), p.get("in")) for p in op_params}
    return [p for p in shared if (p.get("name"), p.get("in")) not in overridden] + op_params


def _convert_response(response: dict, produces: list[str]) -> dict:
    if "$ref" in response:
        return {"$ref": response["$ref"]}
    converted = {"description": response.get("description", "")}
    if "schema" in response:
        converted["content"] = {produces[0]: {"schema": response["schema"]}}
    return converted


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
            params.append(_convert_param(param))
    if form:
        media = "multipart/form-data" if "multipart/form-data" in consumes else "application/x-www-form-urlencoded"
        out["requestBody"] = {"content": {media: {"schema": {"type": "object", "properties": form}}}}
    if params:
        out["parameters"] = params
    out["responses"] = {str(code): _convert_response(response, produces)
                        for code, response in (op.get("responses") or {}).items()}
    return out


def _shared_responses(definitions: dict, produces: list[str]) -> dict:
    produces = produces or ["application/json"]
    return {name: _convert_response(response, produces) for name, response in definitions.items()}


def _shared_parameters(definitions: dict) -> dict:
    return {name: _convert_param(param) for name, param in definitions.items()}


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
                op["parameters"] = _merge_params(shared, op.get("parameters") or [])
                paths[path][method] = _operation(op, doc.get("consumes") or [], doc.get("produces") or [])
    out = {
        "openapi": "3.1.0",
        "info": doc.get("info") or {"title": "imported", "version": "1"},
        "servers": servers,
        "paths": paths,
        "components": {
            "schemas": doc.get("definitions") or {},
            "securitySchemes": _security(doc.get("securityDefinitions") or {}),
            "responses": _shared_responses(doc.get("responses") or {}, doc.get("produces") or []),
            "parameters": _shared_parameters(doc.get("parameters") or {}),
        },
    }
    return _refs(out)
