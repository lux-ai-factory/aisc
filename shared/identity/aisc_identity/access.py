"""Who may do what in a project: the one rule every service applies.

Membership is a row in the platform's core.project_member, one per person per
project, ranked viewer < editor < owner. The realm role `admin` counts as owner
of every project, so a project whose owners have all left can still be managed.

admit() answers with the project it resolved, or raises Refused. A stranger is
told the project does not exist (404) rather than that it is closed (403),
because a slug is often a client's name.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from aisc_identity.caller import Caller

logger = logging.getLogger(__name__)

ADMIN_ROLE = "admin"
ROLES = ("viewer", "editor", "owner")
READS = frozenset({"GET", "HEAD", "OPTIONS"})
WRITES = frozenset({"POST", "PUT", "PATCH", "DELETE"})
MANAGE = "manage"

_RANK = {role: rank for rank, role in enumerate(ROLES)}
_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)

_REFUSALS = {
    "not-found": (404, "No such project."),
    "forbidden": (403, "You can read this project but not change it."),
    "owner-only": (403, "Only an owner can do this."),
    "unavailable": (503, "Who may be here cannot be established just now."),
}


@dataclass(frozen=True)
class Admitted:
    pid: str
    slug: str
    role: str
    admin: bool
    may_write: bool


class Refused(Exception):
    def __init__(self, code: str):
        self.code = code
        self.status, self.message = _REFUSALS[code]
        super().__init__(self.message)


def at_least(role: str | None, needed: str) -> bool:
    """A non-member (None) is not the bottom of the ladder: it is off it."""
    return role in _RANK and _RANK[role] >= _RANK[needed]


def is_pid(ref: str) -> bool:
    return bool(_PID.match(ref or ""))


def admit(ref: str, caller: Caller, want: str, *, connect: Callable) -> Admitted:
    """Admit `caller` to the project named by `ref` for `want`, or raise Refused.

    `ref` is a pid or a slug. A pid-shaped ref is only ever looked up as a pid,
    so a slug that happens to look like another project's pid cannot reach it.
    `want` is an HTTP method (GET, HEAD and OPTIONS read, anything else writes)
    or "manage", which takes an owner. `connect` returns a context manager
    holding a connection to the platform database (psycopg.connect, a pool's
    connection, or contextlib.closing around a raw DB-API connection); any
    error it or the query raises refuses with 503.
    """
    needed = _needed(want)
    try:
        found = _lookup(ref, caller.subject, connect)
    except Exception:
        logger.exception("membership could not be read for %r", ref)
        raise Refused("unavailable") from None
    if found is None:
        raise Refused("not-found")
    pid, slug, member_role = found
    admin = caller.has_role(ADMIN_ROLE)
    role = "owner" if admin else member_role
    if not at_least(role, "viewer"):
        raise Refused("not-found")
    if not at_least(role, needed):
        raise Refused("owner-only" if needed == "owner" else "forbidden")
    return Admitted(pid=pid, slug=slug, role=role, admin=admin, may_write=at_least(role, "editor"))


def _needed(want: str) -> str:
    if want == MANAGE:
        return "owner"
    method = want.upper()
    if method in READS:
        return "viewer"
    if method in WRITES:
        return "editor"
    raise ValueError(f"want is an HTTP method or {MANAGE!r}, not {want!r}")


def _lookup(ref: str, subject: str, connect: Callable) -> tuple[str, str, str | None] | None:
    column = "p.pid" if is_pid(ref) else "p.slug"
    key = ref.lower() if is_pid(ref) else ref
    query = (
        "SELECT p.pid::text, p.slug, m.role FROM core.project p"
        " LEFT JOIN core.project_member m ON m.project_id = p.pid AND m.subject = %s"
        f" WHERE {column} = %s"
    )
    with connect() as conn:
        cursor = conn.cursor()
        cursor.execute(query, (subject, key))
        row = cursor.fetchone()
    if row is None:
        return None
    return tuple(row.values()) if isinstance(row, Mapping) else tuple(row)
