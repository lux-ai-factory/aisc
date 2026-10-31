"""Who is using Superset, as the gateway says.

People sign in once, at the gateway (oauth2-proxy in front of Keycloak). Caddy
asks it about every request and copies the Keycloak access token it holds onto
the request as X-Auth-Request-Access-Token. This verifies that token against the
realm's keys, the way every other module does, and hands Superset the result as
REMOTE_USER, which is what Flask-AppBuilder's AUTH_REMOTE_USER reads. Nothing
the client sends as REMOTE_USER survives: it is only ever set from a verified
token.

No Superset import here, so it tests on its own (test_gateway_identity.py).
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

import jwt

log = logging.getLogger(__name__)

#: Where the verified claims travel with the request, for the role sync.
CLAIMS_KEY = "aisc.gateway_claims"
TOKEN_HEADER = "HTTP_X_AUTH_REQUEST_ACCESS_TOKEN"
#: Named explicitly, as everywhere else: an open list admits `alg: none`.
ALGORITHMS = ["RS256"]
#: Claims a gateway token must carry: without an expiry it would be good forever, and the issue time
#: tells the role sync a newer token from the one it last synced.
REQUIRED_CLAIMS = ["exp", "iat", "iss"]
#: Keycloak signs its ID and refresh tokens with the same keys; only the access token is a Bearer.
ACCESS_TOKEN_TYPE = "Bearer"
#: Waiting longer than this for the realm's keys would hold every Superset request.
JWKS_TIMEOUT_SECONDS = 3


class GatewayIdentity:
    """WSGI middleware: REMOTE_USER from the gateway's verified token."""

    def __init__(self, app, *, issuer: str, client_id: str, jwks_url: str = "",
                 key_for: Optional[Callable[[str], object]] = None):
        if not client_id:
            raise ValueError("client_id: the gateway's Keycloak client is required")
        self.app = app
        self.issuer = issuer
        #: the gateway's own Keycloak client (oauth2-proxy's), from the settings
        self.client_id = client_id
        if key_for is None:
            if not jwks_url:
                raise ValueError("jwks_url: the realm's keys address is required")
            client = jwt.PyJWKClient(jwks_url, timeout=JWKS_TIMEOUT_SECONDS)
            key_for = lambda token: client.get_signing_key_from_jwt(token).key  # noqa: E731
        self.key_for = key_for

    def claims(self, token: str) -> Optional[dict]:
        # Keycloak's access tokens name their client in `azp`; `aud` is the resource servers'
        # ("account"), so the client is checked there, as shared/identity does: a token of the
        # realm issued to another client (the web app's keycloak-js token) is not the gateway's.
        try:
            claims = jwt.decode(token, self.key_for(token), algorithms=ALGORITHMS, issuer=self.issuer,
                                options={"verify_aud": False, "require": REQUIRED_CLAIMS})
        except Exception as exc:  # a bad token is nobody, never an error page
            log.info("gateway token refused: %s", exc)
            return None
        if claims.get("typ") != ACCESS_TOKEN_TYPE:
            log.info("gateway token refused: a %r token, not an access token", claims.get("typ"))
            return None
        if claims.get("azp") != self.client_id:
            log.info("gateway token refused: issued to %r, not the gateway", claims.get("azp"))
            return None
        return claims

    def __call__(self, environ, start_response):
        environ.pop("REMOTE_USER", None)
        environ.pop(CLAIMS_KEY, None)
        token = (environ.get(TOKEN_HEADER) or "").strip()
        claims = self.claims(token) if token else None
        if claims and claims.get("preferred_username"):
            environ["REMOTE_USER"] = claims["preferred_username"]
            environ[CLAIMS_KEY] = claims
        return self.app(environ, start_response)


def what_to_do(signed_in_as: Optional[str], gateway_says: Optional[str]) -> str:
    """How Superset's own session follows the gateway's, on each request."""
    if signed_in_as == gateway_says:
        return "keep"
    if gateway_says is None:
        return "logout"
    return "login" if signed_in_as is None else "switch"


def resync_due(synced_iat: Optional[int], claims: Optional[dict]) -> bool:
    """Whether a session kept for the same person syncs roles again: when the gateway now holds a token
    issued after the one the last sync read, so a role or project change reaches a running session."""
    iat = (claims or {}).get("iat")
    if not isinstance(iat, int) or isinstance(iat, bool):
        return False
    return synced_iat is None or iat > synced_iat
