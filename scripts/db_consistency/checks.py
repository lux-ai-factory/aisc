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


# ── C2 ───────────────────────────────────────────────────────────────────────

KNOWN_DATABASES = {"platform", "keycloak", "superset", "postgres", "control_objectives_test"}
#: The standalone databases the modules used before the one platform database. Reported until
#: someone decides to drop them.
LEFTOVER_DATABASES = {"aisc", "controls", "qualification", "control_objectives"}
KNOWN_PLATFORM_SCHEMAS = {"core", "engine", "qualification", "control_objectives", "report_composer",
                          "catalogue", "public"}


def out_of_scope(name: str) -> bool:
    """The catalogue is not this check's business, wherever it lives."""
    return "catalogue" in name.lower()


def c2_unknown_databases_and_schemas(cl: Cluster) -> list[Finding]:
    """No database, and no schema of the platform database, outside the known list."""
    out = []
    for db in cl.databases():
        if db in KNOWN_DATABASES or PROJECT_DB.match(db) or out_of_scope(db):
            continue
        if db in LEFTOVER_DATABASES:
            out.append(fail("C2", f"database {db} is a leftover standalone database, pending a drop decision"))
        else:
            out.append(fail("C2", f"database {db} is not a known database"))
    schemas = cl.rows(cl.platform_db, "SELECT nspname FROM pg_namespace"
                      " WHERE nspname NOT LIKE 'pg\\_%' AND nspname <> 'information_schema' ORDER BY 1")
    out += [fail("C2", f"schema {s} in {cl.platform_db} is not a known schema")
            for (s,) in schemas if s not in KNOWN_PLATFORM_SCHEMAS and not out_of_scope(s)]
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
    Check("C2", "unknown databases and schemas", "no database or platform schema outside the known list",
          c2_unknown_databases_and_schemas),
]
ALL_CHECKS = DATA_CHECKS
