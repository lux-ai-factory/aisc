"""Who is calling: one answer, shared by every Python service on the platform.

Every service verifies the same Keycloak token the same way, through this
package, so an authorisation decision means the same thing wherever it is made.
"""
from aisc_identity.caller import Caller, IdentityMissing, caller_from_claims
from aisc_identity.headers import GATEWAY_TOKEN_HEADER, token_from_headers
from aisc_identity.service import (
    Misconfigured,
    NotAuthenticated,
    Settings,
    caller_from_headers,
    settings,
)
from aisc_identity.tokens import TokenRejected, verify_token

__all__ = [
    "Caller",
    "GATEWAY_TOKEN_HEADER",
    "IdentityMissing",
    "Misconfigured",
    "NotAuthenticated",
    "Settings",
    "TokenRejected",
    "caller_from_claims",
    "caller_from_headers",
    "settings",
    "token_from_headers",
    "verify_token",
]
