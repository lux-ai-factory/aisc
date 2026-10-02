"""Verifying a Keycloak access token.

No framework and no configuration: the caller says which issuer to trust and
how to find the signing key, which is what makes this testable with a
throwaway key instead of a live Keycloak.
"""
from __future__ import annotations

from typing import Any, Callable

import jwt


class TokenRejected(Exception):
    """The token did not verify. Deliberately one exception: a caller that is
    about to answer 401 does not need to know which way it was wrong, and
    saying so out loud helps whoever sent it."""


#: RS256 only. Naming the algorithms is what stops `alg: none` and the
#: HMAC-with-the-public-key confusion; leaving it open is the classic hole.
ALGORITHMS = ["RS256"]


def verify_token(token: str, *, issuer: str, key_for: Callable[[str], Any], leeway: float = 0) -> dict:
    """The claims of a token that verified, or TokenRejected.

    `key_for` maps the token to the key that signed it, so in production it
    reads Keycloak's JWKS and in a test it is a fixed public key.
    """
    if not token:
        raise TokenRejected("no token")
    try:
        key = key_for(token)
    except Exception as exc:  # a JWKS lookup can fail in many ways
        raise TokenRejected(f"no signing key for this token: {exc}") from exc
    try:
        return jwt.decode(
            token,
            key,
            algorithms=ALGORITHMS,
            issuer=issuer,
            # The audience varies by client (webapp, gateway, controls), and
            # the realm is what we actually care about, so the issuer is the
            # check that matters and the audience is not one.
            options={"verify_aud": False, "require": ["exp", "iss", "sub"]},
            leeway=leeway,
        )
    except jwt.PyJWTError as exc:
        raise TokenRejected(str(exc)) from exc
