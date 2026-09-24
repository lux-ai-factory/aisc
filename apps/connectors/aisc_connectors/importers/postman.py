"""A Postman collection (v2.1) into one operation per request."""
from __future__ import annotations

import json
import re
from typing import Callable

from aisc_connectors.importers import ImportResult
from aisc_connectors.importers.build import merge, one_operation
from aisc_connectors.importers.errors import ImportFailed

_VAR = re.compile(r"\{\{([^}]+)\}\}")


def _requests(items: list, trail: str = ""):
    for item in items:
        if "item" in item:
            yield from _requests(item["item"], trail + item.get("name", "") + " ")
        elif "request" in item:
            yield item.get("name") or trail.strip() or "request", item["request"]


def _auth_values(auth: dict, resolve: Callable[[str], str]) -> dict[str, str]:
    return {entry["key"]: resolve(entry.get("value", "")) for entry in auth.get(auth.get("type"), []) or []}


def _auth_header(auth: dict | None, resolve: Callable[[str], str]) -> dict[str, str]:
    if not auth:
        return {}
    values = _auth_values(auth, resolve)
    if auth.get("type") == "bearer":
        return {"Authorization": f"Bearer {values.get('token', '')}"}
    if auth.get("type") == "apikey" and values.get("in", "header") == "header":
        return {values.get("key", "x-api-key"): values.get("value", "")}
    return {}


def _apikey_query_credential(auth: dict | None, resolve: Callable[[str], str]) -> tuple[str, str] | None:
    """A Postman `apikey` auth with "in": "query" is not a header and is not part of the
    request URL either: it lives only in the auth object. one_operation's query-credential
    detection only recognises a fixed set of parameter names (api_key, token, ...), so routing
    an arbitrary key name (e.g. "X-RapidAPI-Key") through the URL would make it leak into the
    document as an ordinary, visible query parameter. Handle it directly instead: never touch
    the URL or headers, and record the secret straight into the result."""
    if not auth or auth.get("type") != "apikey":
        return None
    values = _auth_values(auth, resolve)
    if values.get("in", "header") != "query":
        return None
    return values.get("key", "api_key"), values.get("value", "")


def import_postman(text: str) -> ImportResult:
    try:
        collection = json.loads(text)
    except ValueError as exc:
        raise ImportFailed("this is not a Postman collection (JSON)") from exc
    variables = {v["key"]: v.get("value", "") for v in collection.get("variable") or []}

    def resolve(value: str) -> str:
        missing = [m for m in _VAR.findall(value) if m not in variables]
        if missing:
            raise ImportFailed(f"the collection uses variables it does not define: {sorted(set(missing))}")
        return _VAR.sub(lambda m: str(variables[m.group(1)]), value)

    results = []
    for name, request in _requests(collection.get("item") or []):
        url = request["url"]["raw"] if isinstance(request.get("url"), dict) else request.get("url", "")
        headers = {h["key"]: resolve(h.get("value", "")) for h in request.get("header") or [] if not h.get("disabled")}
        request_auth = request.get("auth") or collection.get("auth")
        headers.update(_auth_header(request_auth, resolve))
        body, content_type = None, None
        raw_body = request.get("body") or {}
        if raw_body.get("mode") == "raw":
            body = resolve(raw_body.get("raw", ""))
        elif raw_body.get("mode") == "urlencoded":
            body = "&".join(f"{p['key']}={p.get('value', '')}" for p in raw_body["urlencoded"])
            content_type = "application/x-www-form-urlencoded"
        op_id = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "request"
        result = one_operation(request.get("method", "GET"), resolve(url), headers, body, content_type,
                               op_id, summary=name)
        query_credential = _apikey_query_credential(request_auth, resolve)
        if query_credential is not None:
            cred_name, cred_value = query_credential
            result.auth_suggestion = result.auth_suggestion or {"scheme": "api_key", "in": "query", "name": cred_name}
            result.detected_secrets.setdefault("api_key", cred_value)
        results.append(result)
    return merge(results)
