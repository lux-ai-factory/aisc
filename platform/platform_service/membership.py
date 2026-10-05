"""Who may do what inside a project.

Membership is data, not a realm role. A role in Keycloak says what kind of
account this is (may it administer the platform); membership says what this
person is to this project, and there is one of those per project per person, so
it would put the shape of the work into the identity provider.

Three roles, ordered. Only the rules live here: no database, no web framework.
"""
from __future__ import annotations


class InvalidMembership(ValueError):
    """Not one of the three roles, and guessing which was meant would be worse."""


#: Least to most. A role covers everything below it.
ROLES = ("viewer", "editor", "owner")

_RANK = {role: index for index, role in enumerate(ROLES)}


def validate_role(role) -> str:
    if role not in _RANK:
        raise InvalidMembership(f"a role is one of {', '.join(ROLES)}, not {role!r}")
    return role


def at_least(role: str | None, needed: str) -> bool:
    """True when `role` covers `needed`.

    A non-member passes None and is not a viewer: absence is not the bottom of
    the ladder, it is off it.
    """
    if role is None:
        return False
    return _RANK.get(role, -1) >= _RANK[validate_role(needed)]


def may_write(role: str | None) -> bool:
    """Changing the work of the assessment."""
    return at_least(role, "editor")


def may_manage_members(role: str | None) -> bool:
    """Deciding who else is in. Only an owner, so a project cannot be given
    away by somebody who was only invited to help with it."""
    return at_least(role, "owner")
