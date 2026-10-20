"""Shared by every Python service on the platform.

Who is calling (this module, tokens, gateway), what they may do in a project
(access), which service is calling (service_tokens), and the ledger event a
change writes (ledger_events). Every service decides these the same way,
through this package, so a decision means the same thing wherever it is made.
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
