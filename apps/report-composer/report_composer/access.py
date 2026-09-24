"""Who may read and who may change a project's reports (report run 2026-09-23, R4.4).

The pattern of control-objectives' access.py: the platform's core.project_member says what a
person is to a project, read on every request. A realm admin reads every project and edits only
where they are an editor (R4.4.5). No answer from the database means nobody gets in.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

ADMIN_ROLE = "admin"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
Verdict = Literal["allow", "not-found", "forbidden", "unavailable"]


@dataclass(frozen=True)
class Access:
    #: viewer, editor, owner, or None for somebody who is not in the project
    role: str | None
    admin: bool = False

    @property
    def may_write(self) -> bool:
        return self.role in ("editor", "owner")


def decide(method: str, access: Access | None) -> Verdict:
    if access is None:
        return "unavailable"
    if access.role is None and not access.admin:
        # not 403: the slug is the project's name, 403 would confirm it exists
        return "not-found"
    if method.upper() in SAFE_METHODS:
        return "allow"
    return "allow" if access.may_write else "forbidden"


def same_origin(headers, origin: str) -> bool:
    """A write must come from the platform's own pages (R4.4.6)."""
    lowered = {str(k).lower(): v for k, v in dict(headers).items()}
    got = lowered.get("origin")
    if got:
        return got == origin
    referer = lowered.get("referer")
    if referer:
        return referer == origin or referer.startswith(origin + "/")
    return False


def find_project(database_url, ref) -> dict | None:
    """The project named by its pid or its slug, or None."""
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        return conn.execute("SELECT pid::text AS pid, slug, name FROM core.project WHERE pid::text = %s OR slug = %s",
                            (str(ref), str(ref))).fetchone()


def role_in_project(database_url, project_pid, subject) -> str | None:
    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        row = conn.execute("SELECT role FROM core.project_member WHERE project_id = %s AND subject = %s",
                           (str(project_pid), subject)).fetchone()
    return row["role"] if row else None


def access_for(database_url, project, caller) -> Access | None:
    admin = caller.has_role(ADMIN_ROLE)
    try:
        role = role_in_project(database_url, project["pid"], caller.subject)
    except psycopg.Error:
        logger.exception("could not read the membership of a project")
        return None
    return Access(role=role, admin=admin)
