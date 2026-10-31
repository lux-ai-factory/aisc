"""Configuration, and the one call a service makes: who is behind this request.

Settings are read per request rather than at import, so a test can change them
and a container can be reconfigured by restarting it rather than rebuilding it.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from jwt import PyJWKClient

from aisc_identity.caller import Caller, IdentityMissing, caller_from_claims
from aisc_identity.gateway import GatewayRefused, gateway_identity
from aisc_identity.headers import gateway_token, token_from_headers
from aisc_identity.tokens import TokenRejected, verify_token


class NotAuthenticated(Exception):
    """No usable token: the answer is 401 and a chance to sign in."""


class Misconfigured(Exception):
    """Authentication is on and this service cannot verify anything.

    Raised rather than swallowed: a verifier that is not configured must not
    become a verifier that accepts everything.
    """


@dataclass(frozen=True)
class Settings:
    enabled: bool
    issuer: str
    jwks_url: str
    dev_roles: tuple[str, ...]


def _flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def settings() -> Settings:
    roles = os.environ.get("AUTH_DEV_ROLES", "")
    return Settings(
        # Default on. A service that forgets to set this refuses requests,
        # which is noticed immediately; the other default is not noticed at all.
        enabled=_flag("AUTH_ENABLED", "true"),
        issuer=os.environ.get("KEYCLOAK_ISSUER", ""),
        jwks_url=os.environ.get("KEYCLOAK_JWKS_URL", ""),
        dev_roles=tuple(r.strip() for r in roles.split(",") if r.strip()),
    )


def development_caller(roles: tuple[str, ...]) -> Caller:
    """The obviously fake identity local work runs as when AUTH_ENABLED is off.

    It holds no roles unless AUTH_DEV_ROLES says so, so "it worked on my
    machine" cannot mean "because I was admin there".
    """
    return Caller(
        subject="development",
        email="development@localhost",
        username="development",
        roles=roles,
    )


_clients: dict[str, PyJWKClient] = {}

#: How long a JWKS read may take before the token is refused. PyJWKClient's own
#: default is 30 seconds, long enough to hold every request while Keycloak
#: hangs; the keys are cached, so a read happens only every few minutes.
JWKS_TIMEOUT_S = 3


def key_for_jwks(jwks_url: str) -> Callable[[str], Any]:
    """A key resolver reading Keycloak's JWKS, one cached client per URL."""
    client = _clients.get(jwks_url)
    if client is None:
        client = _clients[jwks_url] = PyJWKClient(jwks_url, cache_keys=True, timeout=JWKS_TIMEOUT_S)
    return lambda token: client.get_signing_key_from_jwt(token).key


def caller_from_headers(headers: Mapping[str, str]) -> Caller:
    """The verified caller behind this request.

    Behind the gateway the caller is the person in the gateway's token, by the
    gateway's own rule (aisc_identity.gateway): a Bearer sent next to it must
    name the same person, or the request is refused, so access is never decided
    for another person than the one the gateway signed in and the ledger cites.
    Without the gateway's header the Bearer alone decides.

    Raises NotAuthenticated when there is no usable token, and Misconfigured
    when this service cannot check one.
    """
    config = settings()
    if not config.enabled:
        return development_caller(config.dev_roles)
    if not config.jwks_url or not config.issuer:
        raise Misconfigured(
            "AUTH_ENABLED is on but KEYCLOAK_JWKS_URL / KEYCLOAK_ISSUER are not set"
        )
    key_for = key_for_jwks(config.jwks_url)
    if gateway_token(headers):
        try:
            claims = gateway_identity(headers, issuer=config.issuer, key_for=key_for, gateway_client=None,
                                      leeway=0).claims
        except GatewayRefused as exc:
            raise NotAuthenticated(str(exc)) from exc
    else:
        token = token_from_headers(headers)
        if token is None:
            raise NotAuthenticated("no token")
        try:
            claims = verify_token(token, issuer=config.issuer, key_for=key_for)
        except TokenRejected as exc:
            raise NotAuthenticated(str(exc)) from exc
    try:
        return caller_from_claims(claims)
    except IdentityMissing as exc:
        raise NotAuthenticated(str(exc)) from exc
