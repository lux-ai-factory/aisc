"""OpenAPI 3.x (and Swagger 2.0, via the converter) into the canonical document."""
from __future__ import annotations

import json
import re
from urllib.parse import urljoin, urlsplit

import yaml
from openapi_spec_validator import validate

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.errors import ImportFailed
from aisc_connectors.model import HTTP_METHODS, strip_aisc


def _parse(text: str) -> dict:
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ImportFailed("this is neither JSON nor YAML") from exc
    if not isinstance(data, dict):
        raise ImportFailed("this is not an OpenAPI or Swagger document")
    return data


def _synth_id(method: str, path: str) -> str:
    return method + "_" + (re.sub(r"[^A-Za-z0-9]+", "_", path).strip("_") or "root")


def _server(doc: dict, source_url: str | None, base_url: str | None, warnings: list[str]) -> str:
    if base_url:
        return base_url.rstrip("/")
    servers = doc.get("servers") or []
    url = servers[0]["url"] if servers and servers[0].get("url") else None
    if len(servers) > 1:
        warnings.append(f"the spec lists {len(servers)} servers; using the first, {url}")
    if url and "{" in url:
        for name, var in (servers[0].get("variables") or {}).items():
            url = url.replace("{" + name + "}", str(var.get("default", "")))
    if url and not urlsplit(url).scheme:
        if not source_url:
            raise ImportFailed(f"the server URL {url!r} is relative: give the base URL")
        url = urljoin(source_url, url)
    if not url:
        if not source_url:
            raise ImportFailed("the spec names no server: give the base URL")
        parts = urlsplit(source_url)
        url = f"{parts.scheme}://{parts.netloc}"
        warnings.append(f"the spec names no server; using {url}, where it was downloaded from")
    return url.rstrip("/")


def _auth_suggestion(doc: dict) -> dict | None:
    for scheme in ((doc.get("components") or {}).get("securitySchemes") or {}).values():
        kind = scheme.get("type")
        if kind == "apiKey" and scheme.get("in") in ("header", "query"):
            return {"scheme": "api_key", "in": scheme["in"], "name": scheme["name"]}
        if kind == "http" and scheme.get("scheme", "").lower() == "bearer":
            return {"scheme": "bearer"}
        if kind == "http" and scheme.get("scheme", "").lower() == "basic":
            return {"scheme": "basic", "username": ""}
        if kind == "oauth2" and "clientCredentials" in (scheme.get("flows") or {}):
            return {"scheme": "oauth2_client_credentials",
                    "token_url": scheme["flows"]["clientCredentials"].get("tokenUrl", ""), "client_id": ""}
        if kind == "mutualTLS":
            return {"scheme": "mtls"}
    return None


def import_openapi(text: str, source_url: str | None = None, base_url: str | None = None) -> ImportResult:
    raw = _parse(text)
    if str(raw.get("swagger", "")).startswith("2"):
        from aisc_connectors.importers import swagger2

        raw = swagger2.convert(raw)
    elif not str(raw.get("openapi", "")).startswith("3."):
        raise ImportFailed("this is not an OpenAPI 3.x or Swagger 2.0 document")
    warnings: list[str] = []
    try:
        validate(raw)
    except Exception as exc:  # the validator raises many types; all mean "imperfect"
        warnings.append(f"the spec is not valid OpenAPI ({str(exc).splitlines()[0][:200]}); importing what can be used")
    doc = strip_aisc(raw)
    doc["openapi"] = "3.1.0"
    doc["servers"] = [{"url": _server(raw, source_url, base_url, warnings)}]
    used: set[str] = set()
    for path, item in (doc.get("paths") or {}).items():
        for method in HTTP_METHODS:
            op = (item or {}).get(method)
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId") or _synth_id(method, path)
            while op_id in used:
                op_id += "_"
            used.add(op_id)
            op["operationId"] = op_id
            if op.get("servers"):
                warnings.append(f"{op_id} names its own server; the connector's server is used instead")
            op["x-aisc-binding"] = {"protocol": "http", "method": method, "path": path, "static_headers": {}}
    return ImportResult(document=doc, warnings=warnings, auth_suggestion=_auth_suggestion(raw))
