"""What a connection is, apart from the routes that serve it: the checks of a connection to store, the view of a
stored one, the descriptor the internal routes hand out (never the key) and the one the protocol doors call with
(the key decrypted), the secret headers kept encrypted, the fingerprint a run key carries, and what the Test
button's probes mean."""
from __future__ import annotations

import json
import logging
import re
from urllib.parse import urlsplit

from aisc_identity.headers import token_from_headers
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr

from platform_service import (adapters, connection_allowlist, connection_facade, connection_store, llm_store,
                              target_store)

logger = logging.getLogger(__name__)


# The systems a project assesses over the network. An admin registers, tests and deletes them;
# the engine sees each as a `resource` component `connection:<pid>/<name>`; the plugin-side
# client (aisc_plugin_interface.connections) resolves one on the internal route below.

CONNECTION_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_HEADER_NAME = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_SECRET_HEADERS = {"authorization", "proxy-authorization", "cookie", "x-api-key"}
#: a plain header with a name like these is refused: its value would be stored and shown in the clear
_CREDENTIAL_LIKE = re.compile(r"(?i)(token|secret|passw|api[-_]?key|auth|session|cookie|signature|credential)")
MAX_SECRET_HEADERS = 20
MASK = "***"


class ConnectionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: StrictStr
    kind: StrictStr
    #: required for every kind but `provider`, where only a self-hosted model server has one
    base_url: StrictStr = ""
    #: a provider connection's provider, a key of llm_catalogue.PROVIDERS (kind `provider` only)
    provider: StrictStr | None = None
    method: StrictStr = "POST"
    path: StrictStr = ""
    headers: dict[str, StrictStr] = {}
    secret_header: StrictStr | None = None
    body_template: object | None = None
    response_path: StrictStr | None = None
    refusal: dict | None = None
    model: StrictStr | None = None
    timeout_s: int = 60
    protocol_version: StrictStr | None = None
    secret: StrictStr | None = None
    #: credentials in headers of the connection's own choosing, write-only like `secret`: absent keeps the
    #: stored set, {name: value} sets that header, {name: ""} removes it, names not mentioned are kept
    secret_headers: dict[str, StrictStr] | None = None
    #: an OpenAI-compatible connection's function calling and log probabilities (a PUT without them: false)
    supports_tools: StrictBool = False
    supports_logprobs: StrictBool = False
    #: the assessment target this is the endpoint of ('system' or 'component:<key>'); set once
    target: StrictStr | None = None
    #: an adapter connection's plain fields, {name: value}, as its adapter declares them (stored in body_template)
    settings: dict[str, StrictStr] | None = None
    #: an adapter connection's secret fields, write-only like secret_headers (and stored with them): absent
    #: keeps the stored set, {name: value} sets one, {name: ""} removes it
    secret_settings: dict[str, StrictStr] | None = None


def _invalid_connection(detail: str) -> HTTPException:
    return HTTPException(status_code=422, detail=detail)


def connection_fields(body: ConnectionIn) -> dict:
    """The columns to store, after every check; nothing is written when one fails."""
    label = body.label.strip()
    if not 1 <= len(label) <= 120:
        raise _invalid_connection("label: 1 to 120 characters")
    if body.kind not in adapters.BUILT_IN_KINDS and adapters.get(body.kind) is None:
        raise _invalid_connection(f"kind: {', '.join(adapters.BUILT_IN_KINDS)} or an installed adapter"
                                  f" ({', '.join(adapters.registry()) or 'none installed'})")
    parts = urlsplit(body.base_url.strip())
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise _invalid_connection("base_url: an http(s) URL with a host")
    method = body.method.upper()
    if method not in ("GET", "POST", "PUT"):
        raise _invalid_connection("method: GET, POST or PUT")
    for name, value in body.headers.items():
        if not _HEADER_NAME.fullmatch(name):
            raise _invalid_connection(f"headers: {name!r} is not a header name")
        if "\r" in value or "\n" in value:
            raise _invalid_connection(f"headers: {name}: a header value on one line")
        if name.lower() in _SECRET_HEADERS:
            raise _invalid_connection(f"headers: {name} carries a credential; put it in secret_header")
        if _CREDENTIAL_LIKE.search(name):
            raise _invalid_connection(f"headers: {name} looks like a credential; mark it secret (secret_headers)")
    if body.secret_header is not None:
        if "\r" in body.secret_header or "\n" in body.secret_header:
            raise _invalid_connection("secret_header: 'Name: ...{{secret}}...' on one line")
        name, sep, value = body.secret_header.partition(":")
        if not sep or not _HEADER_NAME.fullmatch(name.strip()) or "{{secret}}" not in value:
            raise _invalid_connection("secret_header: 'Name: ...{{secret}}...'")
    plain = {h.lower() for h in body.headers}
    key_header = body.secret_header.partition(":")[0].strip().lower() if body.secret_header else None
    for name, value in (body.secret_headers or {}).items():
        if not _HEADER_NAME.fullmatch(name):
            raise _invalid_connection(f"secret_headers: {name!r} is not a header name")
        if "\r" in value or "\n" in value or len(value) > 4096:
            raise _invalid_connection(f"secret_headers: {name}: a header value on one line, up to 4096 characters")
        if name.lower() in plain:
            raise _invalid_connection(f"secret_headers: {name} is also a plain header")
        if name.lower() == key_header:
            raise _invalid_connection(f"secret_headers: {name} is where the key goes (secret_header)")
    if not 1 <= body.timeout_s <= 600:
        raise _invalid_connection("timeout_s: 1 to 600")
    adapter = adapters.get(body.kind) if body.kind not in adapters.BUILT_IN_KINDS else None
    if adapter is not None:
        return _adapter_connection_fields(body, adapter, label)
    if body.settings is not None or body.secret_settings is not None:
        raise _invalid_connection("settings and secret_settings: only for a connection of an adapter's kind")
    if body.refusal is not None:
        status = body.refusal.get("status")
        if (not isinstance(status, list) or not status
                or not all(isinstance(x, int) and 100 <= x <= 599 for x in status)
                or not isinstance(body.refusal.get("path", ""), str)
                or not isinstance(body.refusal.get("match", {}), dict)
                or set(body.refusal) - {"status", "path", "match"}):
            raise _invalid_connection("refusal: {status: [codes], path?: str, match?: {path: value}}")
    if body.kind == "rest":
        if not (body.response_path or "").strip():
            raise _invalid_connection("response_path: where the answer is in the response")
        if body.body_template is None and method != "GET":
            raise _invalid_connection("body_template: the request body, with {{input}}")
    if body.kind in ("openai", "oip") and not (body.model or "").strip():
        raise _invalid_connection("model: the model the endpoint serves")
    if body.protocol_version is not None and (body.kind != "a2a" or body.protocol_version not in ("1.0", "0.3")):
        raise _invalid_connection("protocol_version: 1.0 or 0.3, for an a2a connection")
    if body.supports_tools and body.kind != "openai":
        raise _invalid_connection("supports_tools: only an OpenAI-compatible connection carries tools")
    if body.supports_logprobs and body.kind != "openai":
        raise _invalid_connection("supports_logprobs: only an OpenAI-compatible connection carries log probabilities")
    return {"label": label, "kind": body.kind, "base_url": body.base_url.strip().rstrip("/"), "method": method,
            "path": body.path.strip(), "headers": dict(body.headers), "secret_header": body.secret_header,
            "body_template": body.body_template, "response_path": body.response_path,
            "refusal": body.refusal, "model": body.model, "timeout_s": body.timeout_s,
            "protocol_version": body.protocol_version, "supports_tools": body.supports_tools,
            "supports_logprobs": body.supports_logprobs}


#: what a connection of an adapter's kind leaves at its default: the adapter, not the platform, builds the request
_BUILT_IN_ONLY = {"method": "POST", "path": "", "headers": {}, "secret_header": None, "body_template": None,
                  "response_path": None, "refusal": None, "model": None, "protocol_version": None,
                  "secret": None, "secret_headers": None, "supports_tools": False, "supports_logprobs": False}
MAX_SETTING_CHARS = 4096


def _setting_values(what: str, values: dict, allowed: dict, allow_empty: bool) -> None:
    for name, value in values.items():
        if name not in allowed:
            raise _invalid_connection(f"{what}: {name!r} is not one of the adapter's"
                                      f" {'secret ' if what == 'secret_settings' else ''}fields"
                                      f" ({', '.join(allowed) or 'none'})")
        if "\r" in value or "\n" in value or len(value) > MAX_SETTING_CHARS:
            raise _invalid_connection(f"{what}: {name}: a value on one line, up to {MAX_SETTING_CHARS} characters")
        if not value and not allow_empty:
            raise _invalid_connection(f"{what}: {name}: empty")


def _adapter_connection_fields(body: ConnectionIn, adapter, label: str) -> dict:
    """The columns of a connection of an adapter's kind: the common ones, and the plain fields in body_template
    (part of the fingerprint). Built-in-only settings are refused; the secret fields are checked here and
    stored by save_connection."""
    for key, default in _BUILT_IN_ONLY.items():
        if key in body.model_fields_set and getattr(body, key) not in (default, None):
            raise _invalid_connection(f"{key}: not a setting of a {adapter.name} connection (its adapter builds"
                                      " the request)")
    plain = {f.name: f for f in adapter.fields if not f.secret}
    secret = {f.name: f for f in adapter.fields if f.secret}
    settings = dict(body.settings or {})
    _setting_values("settings", settings, plain, allow_empty=False)
    _setting_values("secret_settings", body.secret_settings or {}, secret, allow_empty=True)
    missing = [f.name for f in plain.values() if f.required and f.name not in settings]
    if missing:
        raise _invalid_connection(f"settings: {', '.join(missing)} required")
    return {"label": label, "kind": body.kind, "base_url": body.base_url.strip().rstrip("/"), "method": "POST",
            "path": "", "headers": {}, "secret_header": None, "body_template": settings, "response_path": None,
            "refusal": None, "model": None, "timeout_s": body.timeout_s, "protocol_version": None,
            "supports_tools": False, "supports_logprobs": False}


def connection_view(row: dict) -> dict:
    out = {k: row.get(k) for k in connection_store.PUBLIC}
    for k in ("updated_at", "last_test_at"):
        out[k] = row[k].isoformat() if row.get(k) else None
    out["engine_component"] = str(row["engine_component"]) if row.get("engine_component") else None
    out["has_secret"] = bool(row.get("has_secret"))
    out["secret_headers"] = list(out.pop("secret_header_names", None) or [])
    target = target_store.get(row["pid"], row["target_key"]) if row.get("target_key") and row.get("pid") else None
    out["target"] = {"key": target["key"], "kind": target["kind"], "label": target["label"]} if target else None
    out.pop("target_key", None)
    if row.get("kind") not in adapters.BUILT_IN_KINDS and row.get("kind") != "provider":
        # an adapter's connection: its plain fields, and its secret fields by name only
        out["settings"] = out.pop("body_template", None) or {}
        out["secret_settings"], out["secret_headers"] = out["secret_headers"], []
    return out


LEGACY_MIRROR = "Legacy connection: {label}, pick its target instead"


def retire_engine_component(pid: str, row: dict, request: Request) -> None:
    """A connection made before targets had an engine component of its own; evaluations now pick
    the target's instead (O1). The old one is kept, for the evaluations that used it, and renamed
    so the evaluation form says what to pick instead."""
    if row.get("engine_component") is None:
        return
    from platform_service import engine_components
    try:
        engine_components.rename(pid, token_from_headers(request.headers) or "", str(row["engine_component"]),
                                 LEGACY_MIRROR.format(label=row["label"]))
    except engine_components.EngineUnavailable as exc:
        logger.warning("legacy engine component of connection %s (project %s) not renamed: %s",
                       row["name"], pid, exc)


def _stored_secret_headers(row: dict | None) -> dict[str, str]:
    """The decrypted secret headers of a stored connection; {} without any."""
    token = (row or {}).get("secret_headers_ciphertext")
    return json.loads(llm_store.decrypt((row or {}).get("name") or "", token)) if token else {}


def _merged_secret_headers(pid: str, name: str, change: dict[str, str]):
    """(names, ciphertext) of the stored set with `change` applied ("" removes a name), or (names, KEEP)
    when nothing changes. 503 without the secrets key, 409 for a stored set no key decrypts, 422 over
    MAX_SECRET_HEADERS."""
    try:
        values = _stored_secret_headers(connection_store.descriptor(pid, name))
        merged = dict(values)
        for header, value in change.items():
            if value:
                merged[header] = value
            else:
                merged.pop(header, None)
        if len(merged) > MAX_SECRET_HEADERS:
            raise _invalid_connection(f"secret_headers: up to {MAX_SECRET_HEADERS}")
        if merged == values:
            return sorted(values), connection_store.KEEP
        return sorted(merged), (llm_store.encrypt(json.dumps(merged, sort_keys=True)) if merged else None)
    except llm_store.SecretsKeyError as exc:
        # the routes' answer to a missing secrets key; imported here, since the routes import this module
        from platform_service.routes.admission import secrets_unavailable
        raise secrets_unavailable(exc) from None
    except llm_store.KeyUnreadable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None


def descriptor_of(row: dict, pid: str | None = None) -> dict:
    """What anyone the internal routes let in may see of a connection: every setting, whether it has a key
    (`has_secret`), never the key itself, and the target it is the endpoint of (part of what the
    connection is, so of its fingerprint). Nothing is decrypted here."""
    # `provider` is left out: only a provider connection has one, and it never reaches the assessed system (and so
    # the view, and the fingerprint made of it, stay what they were before provider connections existed)
    out = {k: row.get(k) for k in connection_store.PUBLIC if k not in ("engine_component", "last_test_at",
                                                                       "last_test_ok", "last_test_detail",
                                                                       "target_key", "provider")}
    out["updated_at"] = row["updated_at"].isoformat() if row.get("updated_at") else None
    # the secret headers by name, their values masked: the fingerprint and the client's copy hold none
    out["headers"] = {**(out.get("headers") or {}), **{h: MASK for h in out.pop("secret_header_names", None) or []}}
    out["has_secret"] = row.get("secret_ciphertext") is not None
    out["target"] = _target_of(pid, row) if pid else None
    return out


def call_descriptor_of(row: dict, pid: str | None = None):
    """The plugin-interface Descriptor to call the system with, the key decrypted: the one place a key is
    read back, for the protocol doors and the Test button. Raises llm_store.SecretsKeyError or
    llm_store.KeyUnreadable."""
    from aisc_plugin_interface import connections as client

    out = descriptor_of(row, pid)
    out["secret"] = llm_store.decrypt(row["name"], row["secret_ciphertext"]) if row.get("secret_ciphertext") else None
    secret_headers = _stored_secret_headers(row)
    out["headers"] = {**out["headers"], **secret_headers}
    descriptor = client.Descriptor.from_dict(out)
    descriptor.secret_header_names = sorted(secret_headers)       # for secret_values
    return descriptor


def adapter_connection_of(descriptor) -> dict:
    """What an adapter is given of its connection: the common settings, its plain fields and its secret ones
    (decrypted: call_descriptor_of put them among the headers)."""
    headers = descriptor.headers or {}
    return {"name": descriptor.name, "label": descriptor.label, "base_url": descriptor.base_url,
            "timeout_s": descriptor.timeout_s, "settings": dict(descriptor.body_template or {}),
            "secrets": {n: headers[n] for n in getattr(descriptor, "secret_header_names", []) if n in headers}}


def secret_values(descriptor) -> list[str]:
    """The values to scrub from any error text of a call with this descriptor: its key and the values of
    its secret headers."""
    headers = descriptor.headers or {}
    values = [descriptor.secret] + [headers.get(h) for h in getattr(descriptor, "secret_header_names", [])]
    return [v for v in values if v]


_PROBE_ERRORS = connection_facade.ERROR_CODES


def _reached_by_ping(descriptor, sent, exc) -> bool:
    """A `ping` checks that the system is reached and takes the key. A chat answers it; a system whose whole
    request body is the input (a scorer) answers a 4xx, since "ping" is not a request it understands: that
    answer comes from the system itself, after the key was accepted. 401, 403 and 404 are still failures."""
    whole_body = descriptor.kind == "rest" and isinstance(descriptor.body_template, str) \
        and descriptor.body_template.strip() == "{{input}}"
    status = getattr(exc, "status", None)
    return sent == "ping" and whole_body and status is not None and 400 <= status < 500 \
        and status not in (401, 403, 404)


#: the function the Test button asks a connection that carries tools to call
PROBE_TOOL = {"type": "function", "function": {"name": "aisc_probe", "description": "Answers that the endpoint calls tools.",
                                               "parameters": {"type": "object", "properties": {}}}}


def _capability_checks(pid: str, row: dict, descriptor) -> dict:
    """One more probe per capability the connection says it has, tools before logprobs: {name: {ok, detail}};
    {} without any."""
    from aisc_plugin_interface import connections as client

    checks = {}
    secrets = secret_values(descriptor)
    if row.get("supports_tools"):
        try:
            answer = client.call(descriptor, "Call the function aisc_probe.", None, params={
                "tools": [PROBE_TOOL], "tool_choice": {"type": "function", "function": {"name": "aisc_probe"}}},
                waits=(), **connection_allowlist.rule(pid))
            called = any(isinstance(c, dict) and (c.get("function") or {}).get("name") == "aisc_probe"
                         for c in answer.tool_calls or [])
            checks["tools"] = {"ok": True, "detail": "called aisc_probe"} if called else {
                "ok": False, "detail": "tools: the endpoint answered without calling the function it was asked to call"}
        except client.EndpointError as exc:
            checks["tools"] = {"ok": False, "detail": f"tools: {connection_facade.error_code(exc)}: "
                                                      f"{connection_facade.scrub(str(exc), secrets)}"}
    if row.get("supports_logprobs"):
        try:
            client.call(descriptor, "ping", None, params={"logprobs": True, "top_logprobs": 1}, waits=(),
                        **connection_allowlist.rule(pid))
            checks["logprobs"] = {"ok": True,
                                  "detail": "the endpoint accepted logprobs: true; the log probabilities are not read"}
        except client.EndpointError as exc:
            status = getattr(exc, "status", None)
            checks["logprobs"] = {"ok": False, "detail": (
                f"logprobs: the endpoint refused logprobs: true ({status})" if status is not None else
                f"logprobs: {connection_facade.error_code(exc)}: {connection_facade.scrub(str(exc), secrets)}")}
    return checks


def _target_of(pid: str, row: dict) -> dict | None:
    target = target_store.get(pid, row["target_key"]) if row.get("target_key") else None
    if target is None:
        return None
    return {"key": target["key"], "kind": target["kind"], "component_kind": target["component_kind"],
            "label": target["label"], "last_card_number": target["last_card_number"]}


def _fingerprint_of(descriptor: dict) -> str:
    """The plugin-side Descriptor fingerprint of a connection as descriptor_of gives it, what a run key
    and a recorded use both carry."""
    from aisc_plugin_interface import connections as client
    return client.Descriptor.from_dict(descriptor).fingerprint()
