"""The roles a person can hold in a project, as the member routes accept them.

Membership is data, not a realm role: a Keycloak role says what kind of account
this is, membership says what this person is to one project. The ranking and
who may do what are aisc_identity.access's; this only validates what a caller
asks to set.
"""
from __future__ import annotations

from aisc_identity.access import ROLES


class InvalidMembership(ValueError):
    """Not one of the three roles, and guessing which was meant would be worse."""


def validate_role(role) -> str:
    if role not in ROLES:
        raise InvalidMembership(f"a role is one of {', '.join(ROLES)}, not {role!r}")
    return role
