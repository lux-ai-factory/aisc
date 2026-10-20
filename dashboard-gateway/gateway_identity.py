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
            client = jwt.PyJWKClient(jwks_url)
            key_for = lambda token: client.get_signing_key_from_jwt(token).key  # noqa: E731
        self.key_for = key_for

    def claims(self, token: str) -> Optional[dict]:
        # Keycloak's access tokens name their client in `azp`; `aud` is the resource servers'
        # ("account"), so the client is checked there, as shared/identity does: a token of the
        # realm issued to another client (the web app's keycloak-js token) is not the gateway's.
        try:
            claims = jwt.decode(token, self.key_for(token), algorithms=ALGORITHMS,
                                issuer=self.issuer, options={"verify_aud": False})
        except Exception as exc:  # a bad token is nobody, never an error page
            log.info("gateway token refused: %s", exc)
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
