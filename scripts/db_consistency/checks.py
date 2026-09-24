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


# ── C3 ───────────────────────────────────────────────────────────────────────

#: qualification.qualification column, the core.system column it repeats
CARD_FIELDS = (("systemName", "name"), ("systemVersion", "version"), ("company", "provider"))


def c3_system_identity(cl: Cluster) -> list[Finding]:
    """A card version's name, version and provider read the same in core, qualification and
    control objectives. core.system's NULL version or provider is the card's empty string; an
    assessment is named "<name> <version>", or "<name>" when there is no version."""
    out = []
    db = cl.platform_db
    if cl.exists(db, "qualification.qualification"):
        rows = cl.rows(db, """
            SELECT s.pid::text, p.slug, s.number, q.id,
                   q."systemName", s.name, q."systemVersion", coalesce(s.version, ''),
                   q.company, coalesce(s.provider, '')
              FROM qualification.qualification q
              JOIN core.system s ON s.pid = q.system_id
              JOIN core.project p ON p.pid = s.project_id
             ORDER BY p.slug, s.number""")
        for pid, slug, number, qid, *values in rows:
            for i, (qcol, scol) in enumerate(CARD_FIELDS):
                card, core = values[2 * i], values[2 * i + 1]
                if card != core:
                    out.append(fail("C3", f"system {pid} ({slug} v{number}): qualification {qid} "
                                          f"{qcol} is '{card}', core.system {scol} is '{core}'"))
    if cl.exists(db, "control_objectives.project"):
        rows = cl.rows(db, """
            SELECT s.pid::text, p.slug, s.number, a.id, a.name,
                   s.name || CASE WHEN coalesce(s.version, '') <> '' THEN ' ' || s.version ELSE '' END
              FROM control_objectives.project a
              JOIN core.system s ON s.pid = a.system_id
              JOIN core.project p ON p.pid = s.project_id
             WHERE a.name IS DISTINCT FROM
                   s.name || CASE WHEN coalesce(s.version, '') <> '' THEN ' ' || s.version ELSE '' END
             ORDER BY p.slug, s.number""")
        out += [fail("C3", f"system {pid} ({slug} v{number}): control_objectives project {aid} is named "
                           f"'{name}', core.system says '{want}'")
                for pid, slug, number, aid, name, want in rows]
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
    Check("C3", "system identity", "every card version has one name, version and provider",
          c3_system_identity),
]
ALL_CHECKS = DATA_CHECKS
