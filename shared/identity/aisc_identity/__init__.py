"""Shared by every Python service on the platform.

Who is calling (this module, tokens, gateway), what they may do in a project
(access), which service is calling (service_tokens), the ledger event a change
writes (ledger_events), and a project's database name and address (projectdb). Every service decides these the same way,
through this package, so a decision means the same thing wherever it is made.
"""
from importlib import import_module

#: where each name of the package lives. Loaded on first use (PEP 562), so a module of the package that needs only
#: the standard library (canonical) can be imported without pyjwt.
_NAMES = {
    "Caller": "caller", "IdentityMissing": "caller", "caller_from_claims": "caller",
    "GATEWAY_TOKEN_HEADER": "headers", "token_from_headers": "headers",
    "Misconfigured": "service", "NotAuthenticated": "service", "Settings": "service",
    "caller_from_headers": "service", "settings": "service",
    "TokenRejected": "tokens", "verify_token": "tokens",
}


def __getattr__(name):
    if name in _NAMES:
        return getattr(import_module(f"aisc_identity.{_NAMES[name]}"), name)
    raise AttributeError(f"module 'aisc_identity' has no attribute {name!r}")


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
