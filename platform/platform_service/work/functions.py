"""Who may hold which function in a project, and who may give or take it.

A function decides whose work a member may check, so these rules are part of the control. Each
function returns a refusal code, or None when the change is allowed.
"""
from __future__ import annotations

import re

AUDIT = "audit"
_NAME = re.compile(r"^[a-z][a-z0-9_]{1,39}$")


def _may_manage(actor_role, actor_is_admin) -> bool:
    return actor_is_admin or actor_role == "owner"


def grant_allowed(*, actor_subject: str, actor_role: str | None, actor_is_admin: bool, member_subject: str,
                  member_role: str, held: list, function: str, catalogue: dict) -> str | None:
    """Whether `actor` may give `function` to a member who holds `held`. `catalogue` maps names to lines."""
    if not _may_manage(actor_role, actor_is_admin):
        return "owner_only"
    if actor_subject == member_subject:
        return "own_functions"
    if function not in catalogue:
        return "unknown_function"
    others = [f for f in held if f != function]
    if function == AUDIT and others or AUDIT in others:
        return "audit_alone"
    if function == AUDIT and member_role != "viewer":
        return "audit_viewer_only"
    if any(catalogue.get(f) != catalogue[function] for f in others):
        return "mixed_lines"
    return None


def removal_allowed(*, actor_subject: str, actor_role: str | None, actor_is_admin: bool,
                    member_subject: str) -> str | None:
    if not _may_manage(actor_role, actor_is_admin):
        return "owner_only"
    if actor_subject == member_subject:
        return "own_functions"
    return None


def role_change_allowed(*, held: list, new_role: str) -> str | None:
    """A member who holds audit stays a viewer while they hold it."""
    if AUDIT in held and new_role != "viewer":
        return "audit_viewer_only"
    return None


def grant_loosening(function: str, catalogue: dict) -> list[str]:
    """Giving a line 2 or line 3 function adds someone who may check: a loosening."""
    return ["checker_added"] if catalogue.get(function, 1) >= 2 else []


def line_of(held: list, catalogue: dict) -> int | None:
    lines = {catalogue[f] for f in held if f in catalogue}
    return min(lines) if lines else None


def name_allowed(name: str) -> bool:
    return isinstance(name, str) and bool(_NAME.match(name))


def line_allowed(line: int) -> bool:
    """A project adds functions to the first two lines only; the third holds audit alone."""
    return line in (1, 2)
