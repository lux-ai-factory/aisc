"""The ledger event an app writes about a change, and the request it cites.

An app writes its events with its project database's `ledger.emit(jsonb)`, in the
transaction of the change itself, so a rollback leaves no event and a committed
change always has one. An event never names who acted: it cites the request the
gateway witnessed (X-AISC-Request-Id), and the platform's relay takes the person
from that record. Nothing is written while LEDGER_MODE is off; `record` and
`enforce` turn it on.

RequestId keeps a presented request id only on a request that carries a gateway
token that verifies by the witness's own rule (aisc_identity.gateway): a caller
reaching the app directly, with no token or one of its own, could otherwise make
an event cite any request it names. With AUTH_ENABLED off nothing is verified
anywhere, and the presented id is kept.

event() refuses, with NotLedgerSafe, any value the relay would reject later:
integers beyond 2**53, NaN and infinities, lone surrogates, and types JSON has
no form for. Each app keeps its own emit(), a few lines for its database driver.
"""
from __future__ import annotations

import contextvars
import math
import os
import uuid
from typing import Any

#: The witnessed request being served, or None outside one.
current_request: contextvars.ContextVar[str | None] = contextvars.ContextVar("ledger_request", default=None)

EMIT_SQL = "SELECT ledger.emit(%s::jsonb)"

_MAX_SAFE = 2 ** 53
_OPTIONAL = ("content", "before", "after", "run_id", "model", "item_version", "card_version")


class NotLedgerSafe(ValueError):
    pass


def on() -> bool:
    return (os.environ.get("LEDGER_MODE") or "off").strip().lower() in ("record", "enforce")


def event(action: str, *, item_type: str, item_id: str | None, details: dict | None = None,
          **optional: Any) -> dict:
    """The event as ledger.emit takes it. `optional` takes content, before, after, run_id, model,
    item_version and card_version; a None value is left out."""
    unknown = set(optional) - set(_OPTIONAL)
    if unknown:
        raise TypeError(f"not an event field: {', '.join(sorted(unknown))}")
    body: dict[str, Any] = {"event_id": str(uuid.uuid4()), "request_id": current_request.get(),
                            "action": action, "item_type": item_type, "item_id": item_id,
                            "details": details or {}}
    body.update({key: value for key, value in optional.items() if value is not None})
    _check(body)
    return body


def _check(value: Any) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, int):
        if abs(value) > _MAX_SAFE:
            raise NotLedgerSafe(f"integer beyond 2**53: {value}")
    elif isinstance(value, float):
        if not math.isfinite(value) or (value.is_integer() and abs(value) > _MAX_SAFE):
            raise NotLedgerSafe(f"a number the ledger can't keep: {value}")
    elif isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise NotLedgerSafe("a lone surrogate has no UTF-8 form") from None
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _check(key)
            _check(item)
    else:
        raise NotLedgerSafe(f"JSON has no form for {type(value).__name__}")


def _through_gateway(headers: dict[bytes, bytes]) -> bool:
    from aisc_identity import service
    from aisc_identity.gateway import GatewayRefused, gateway_identity

    config = service.settings()
    if not config.enabled:
        return True
    if not config.issuer or not config.jwks_url:
        return False
    text_headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in headers.items()}
    try:
        gateway_identity(text_headers, issuer=config.issuer, key_for=service.key_for_jwks(config.jwks_url),
                         gateway_client=os.environ.get("AISC_GATEWAY_CLIENT_ID", "aisc-gateway"))
    except GatewayRefused:
        return False
    return True


class RequestId:
    """ASGI middleware: the witnessed request id, for the events of the request being served."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        presented = headers.get(b"x-aisc-request-id")
        value = None
        if presented and _through_gateway(headers):
            try:
                value = str(uuid.UUID(presented.decode("latin-1")))
            except ValueError:
                value = None
        token = current_request.set(value)
        try:
            return await self.app(scope, receive, send)
        finally:
            current_request.reset(token)
