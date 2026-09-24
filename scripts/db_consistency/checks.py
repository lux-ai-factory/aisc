"""The checks, C1 to C8. Each takes a Cluster and returns a list of findings; an empty list
means the check passed. Only SELECTs, on read-only connections (cluster.py)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from .cluster import Cluster
from .findings import Finding, fail, warn

PROJECT_DB = re.compile(r"^project_[0-9a-f]{32}$")


def project_databases(cl: Cluster) -> list[str]:
    return [d for d in cl.databases() if PROJECT_DB.match(d)]


def core_projects(cl: Cluster) -> dict[str, tuple[str, str]]:
    """Every core.project: the database name it should have, to (pid, slug)."""
    rows = cl.rows(cl.platform_db, "SELECT pid::text, slug FROM core.project ORDER BY slug")
    return {"project_" + pid.replace("-", ""): (pid, slug) for pid, slug in rows}


# ── C1 ───────────────────────────────────────────────────────────────────────

def c1_orphan_databases(cl: Cluster) -> list[Finding]:
    """Every project database belongs to a project, and every project has its database."""
    dbs = set(project_databases(cl))
    projects = core_projects(cl)
    out = [fail("C1", f"{db} has no core.project row: an orphan database")
           for db in sorted(dbs - projects.keys())]
    out += [fail("C1", f"core.project {pid} ({slug}) has no database {db}")
            for db, (pid, slug) in sorted(projects.items()) if db not in dbs]
    return out


# ── the registry ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Check:
    id: str
    name: str   # the heading
    title: str  # what a PASS says
    fn: Callable[[Cluster], list[Finding]]

    def run(self, cl: Cluster) -> list[Finding]:
        return self.fn(cl)


DATA_CHECKS = [
    Check("C1", "orphan databases", "every project database belongs to a project", c1_orphan_databases),
]
ALL_CHECKS = DATA_CHECKS
