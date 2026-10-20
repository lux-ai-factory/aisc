"""The door of a service that other services call.

The backend network is not a trust boundary: the engine's worker runs plugin
code there, and that code can open a socket to every service by name. So each
caller holds a token of its own, one per caller edge, sent in
X-AISC-Service-Token.

identify() says which caller a token belongs to. Every configured token is
compared in constant time, whatever the first answer. The door fails closed. A
caller whose token is not set cannot match, so it is refused like any wrong
token (401), and the callers that are configured keep working: a prober learns
nothing about the configuration. 503 only when no token is set at all, or two
are the same value (one shared token under two names).

The sidecars are built from their own folders and cannot import aisc_identity,
so each carries a copy of this file as service_token.py. It imports nothing
but the standard library and Starlette, and scripts/tests/test_service_tokens.py
keeps every copy identical to this one.
"""
from __future__ import annotations

import hmac
import os
from collections.abc import Mapping

from starlette.datastructures import Headers
from starlette.responses import JSONResponse

HEADER = "x-aisc-service-token"
OPEN_PATHS = frozenset({"/health"})


class ServiceRefused(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


def identify(given: str | None, callers: Mapping[str, str], env: Mapping[str, str] = os.environ) -> str:
    """The caller whose token was sent; `callers` maps each caller to the variable holding its token."""
    expected = {caller: env[name] for caller, name in callers.items() if env.get(name)}
    if not expected:
        raise ServiceRefused(503, "this service is closed: its service tokens are not set")
    if len(set(expected.values())) < len(expected):
        raise ServiceRefused(503, "this service is closed: its service tokens must differ")
    found = None
    for caller, token in expected.items():
        if hmac.compare_digest((given or "").encode(), token.encode()):
            found = caller
    if found is None:
        raise ServiceRefused(401, "a service token is needed")
    return found


class ServiceTokens:
    """ASGI middleware: `app.add_middleware(ServiceTokens, names=("A_TO_B_TOKEN", ...))`.

    `names` are the variables holding the callers' tokens, read on every
    request so a rotated secret is seen after a restart and a test sees its own.
    """

    def __init__(self, app, names: tuple[str, ...], header: str = HEADER,
                 open_paths: frozenset[str] = OPEN_PATHS):
        self.app = app
        self.names = tuple(names)
        self.header = header
        self.open_paths = open_paths

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":
            await self.app(scope, receive, send)
            return
        if scope["type"] != "http":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["path"] in self.open_paths:
            await self.app(scope, receive, send)
            return
        try:
            identify(Headers(scope=scope).get(self.header), {name: name for name in self.names})
        except ServiceRefused as refused:
            response = JSONResponse({"detail": refused.detail}, status_code=refused.status,
                                    headers={"Cache-Control": "no-store"})
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
