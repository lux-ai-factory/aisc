"""The caller: the handful of claims the platform makes decisions with.

Kept to what is actually used, so a change in the identity provider touches one
small shape rather than every service that reads a token.
"""
from __future__ import annotations

from dataclasses import dataclass


class IdentityMissing(ValueError):
    """The claims verified but do not name anybody."""


@dataclass(frozen=True)
class Caller:
    #: Keycloak's stable subject. Every authorisation decision keys on this and
    #: never on the email, which a person can change.
    subject: str
    email: str | None
    username: str | None
    roles: tuple[str, ...]

    def has_role(self, role: str) -> bool:
        return role in self.roles


def caller_from_claims(claims: dict) -> Caller:
    subject = claims.get("sub")
    if not subject:
        raise IdentityMissing("the token names no subject")
    realm = claims.get("realm_access") or {}
    return Caller(
        subject=subject,
        email=claims.get("email"),
        username=claims.get("preferred_username"),
        roles=tuple(realm.get("roles") or ()),
    )
