"""Where a token arrives from.

Two ways in, and they are the same token: an API client sends `Authorization:
Bearer`, and a page behind the gateway holds no session of its own, so
oauth2-proxy passes the token it holds under its own header name.
"""
from __future__ import annotations

from typing import Mapping

#: Set by oauth2-proxy with --pass-access-token and copied through by Caddy.
GATEWAY_TOKEN_HEADER = "X-Auth-Request-Access-Token"


def gateway_token(headers: Mapping[str, str]) -> str | None:
    """The token the gateway passed, or None when the request did not come through it."""
    lowered = {str(k).lower(): v for k, v in headers.items()}
    return (lowered.get(GATEWAY_TOKEN_HEADER.lower()) or "").strip() or None


def token_from_headers(headers: Mapping[str, str]) -> str | None:
    lowered = {str(k).lower(): v for k, v in headers.items()}
    authorization = (lowered.get("authorization") or "").strip()
    if authorization.lower().startswith("bearer "):
        token = authorization[len("bearer "):].strip()
        if token:
            return token
    return gateway_token(headers)
