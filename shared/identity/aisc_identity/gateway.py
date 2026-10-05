"""Who a request behind the gateway is: one rule, for the ledger's witness and for every app that
uses it.

- The gateway token (X-Auth-Request-Access-Token, set by oauth2-proxy and copied in by Caddy) is
  authoritative. It must verify, and it must have been issued to the gateway's own client (`azp`).
- A Bearer token on the same request must verify too and carry the same `sub`. It may come from
  another client (the engine's web app sends its keycloak-js token), so its `azp` is not checked.
  Otherwise the request is refused: an app that prefers the Bearer would act as another person than
  the one the gateway signed in.
- `leeway` covers a token that expires while the request crosses the gateway.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from aisc_identity.headers import GATEWAY_TOKEN_HEADER
from aisc_identity.tokens import TokenRejected, verify_token


class GatewayRefused(Exception):
    """Why a gateway request has no person: `missing`, `invalid`, `other_client` or `token_mismatch`."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass(frozen=True)
class GatewayIdentity:
    subject: str
    username: str
    token_id: str | None
    expires_at: int
    claims: dict


def _header(headers: Mapping[str, str], name: str) -> str:
    lowered = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lowered:
            return (value or "").strip()
    return ""


def gateway_identity(headers: Mapping[str, str], *, issuer: str, key_for: Callable[[str], Any],
                     gateway_client: str, leeway: float = 30) -> GatewayIdentity:
    token = _header(headers, GATEWAY_TOKEN_HEADER)
    if not token:
        raise GatewayRefused("missing", "no gateway token")
    try:
        claims = verify_token(token, issuer=issuer, key_for=key_for, leeway=leeway)
    except TokenRejected as exc:
        raise GatewayRefused("invalid", str(exc)) from exc
    if claims.get("azp") != gateway_client:
        raise GatewayRefused("other_client", f"issued to {claims.get('azp')!r}, not the gateway")
    authorization = _header(headers, "Authorization")
    if authorization:
        bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        try:
            other = verify_token(bearer, issuer=issuer, key_for=key_for, leeway=leeway)
        except TokenRejected as exc:
            raise GatewayRefused("invalid", f"the Bearer token: {exc}") from exc
        if other.get("sub") != claims.get("sub"):
            raise GatewayRefused("token_mismatch", "the Bearer token names another person")
    return GatewayIdentity(subject=claims["sub"], username=claims.get("preferred_username") or claims["sub"],
                           token_id=claims.get("jti"), expires_at=int(claims["exp"]), claims=claims)
