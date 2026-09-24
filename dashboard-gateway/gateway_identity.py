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


class GatewayIdentity:
    """WSGI middleware: REMOTE_USER from the gateway's verified token."""

    def __init__(self, app, *, issuer: str, jwks_url: str = "",
                 key_for: Optional[Callable[[str], object]] = None):
        self.app = app
        self.issuer = issuer
        if key_for is None:
            client = jwt.PyJWKClient(jwks_url)
            key_for = lambda token: client.get_signing_key_from_jwt(token).key  # noqa: E731
        self.key_for = key_for

    def claims(self, token: str) -> Optional[dict]:
        try:
            return jwt.decode(token, self.key_for(token), algorithms=["RS256"],
                              issuer=self.issuer, options={"verify_aud": False})
        except Exception as exc:  # a bad token is nobody, never an error page
            log.info("gateway token refused: %s", exc)
            return None

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
