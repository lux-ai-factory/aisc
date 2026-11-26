"""Who may change a project's controls, and when a change waits for a second person.

The owner of a project is usually one of the people whose work the rules are about, so a change that
lowers control is proposed with a reason and confirmed by someone else.
"""
from __future__ import annotations

WHAT = ("rule", "tier", "function", "floor")


def _check_what(what: str) -> None:
    if what not in WHAT:
        raise ValueError(f"a change of controls is one of {', '.join(WHAT)}, not {what!r}")


def _may_act(what, actor_role, actor_is_admin) -> str | None:
    if what == "floor":
        return None if actor_is_admin else "admin_only"
    return None if actor_is_admin or actor_role == "owner" else "owner_only"


def decide(*, actor_subject: str, actor_role: str | None, actor_is_admin: bool, what: str, loosening: list,
           reason: str) -> str:
    """allowed, needs_second_person, or a refusal code."""
    _check_what(what)
    refused = _may_act(what, actor_role, actor_is_admin)
    if refused:
        return refused
    if not loosening:
        return "allowed"
    if not (reason or "").strip():
        return "reason_required"
    return "needs_second_person"


def may_confirm(*, actor_subject: str, actor_role: str | None, actor_is_admin: bool, proposed_by: str,
                what: str) -> str | None:
    """Someone other than the proposer, with the right to make the change themselves."""
    _check_what(what)
    refused = _may_act(what, actor_role, actor_is_admin)
    if refused:
        return refused
    return "same_person" if actor_subject == proposed_by else None


def may_reject(*, actor_subject: str, actor_role: str | None, actor_is_admin: bool, proposed_by: str,
               what: str) -> str | None:
    """As confirming, except that the proposer may withdraw their own proposal."""
    _check_what(what)
    if actor_subject == proposed_by:
        return None
    return _may_act(what, actor_role, actor_is_admin)


def acted_as(*, actor_role: str | None, actor_is_admin: bool) -> str:
    """How a change is recorded: as admin when the person has no role in the project, else as owner."""
    return "admin" if actor_is_admin and actor_role is None else "owner"
