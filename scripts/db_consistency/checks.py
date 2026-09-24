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


# ── C4 ───────────────────────────────────────────────────────────────────────

#: Tables that name both a project and a card version: the version must be of that project.
PAIRED = ("qualification.qualification", "control_objectives.project",
          "report_composer.layout", "report_composer.generated_report")


def _paired(cl: Cluster, table: str) -> list[Finding]:
    rows = cl.rows(cl.platform_db, f"""
        SELECT t.id::text, t.project_id::text, t.system_id::text, s.pid IS NULL, s.project_id::text
          FROM {table} t LEFT JOIN core.system s ON s.pid = t.system_id
         WHERE s.pid IS NULL OR s.project_id <> t.project_id
         ORDER BY 1""")
    return [fail("C4", f"{table} {rid}: system_id {sid} is not a core.system") if dangling else
            fail("C4", f"{table} {rid}: system {sid} belongs to another project ({owner}) "
                       f"than the row's project_id {pid}")
            for rid, pid, sid, dangling, owner in rows]


def _engine(cl: Cluster) -> list[Finding]:
    db, out = cl.platform_db, []
    if cl.exists(db, "engine.project"):
        for pid, name, project in cl.rows(db, """
                SELECT e.pid::text, e.name, e.project_id::text FROM engine.project e
                  LEFT JOIN core.project c ON c.pid = e.project_id
                 WHERE c.pid IS NULL ORDER BY e.id"""):
            if project is None:
                out.append(warn("C4", f"engine.project {pid} ({name}) has no platform project (project_id is NULL)"))
            else:
                out.append(fail("C4", f"engine.project {pid} ({name}): project_id {project} is not a core.project"))
    if cl.exists(db, "engine.evaluation"):
        for pid, sid, dangling, owner, project in cl.rows(db, """
                SELECT e.pid::text, e.system_id::text, s.pid IS NULL, s.project_id::text, ep.project_id::text
                  FROM engine.evaluation e
                  JOIN engine.project ep ON ep.id = e.project_id
                  LEFT JOIN core.system s ON s.pid = e.system_id
                 WHERE e.system_id IS NOT NULL
                   AND (s.pid IS NULL OR s.project_id IS DISTINCT FROM ep.project_id)
                 ORDER BY e.id"""):
            if dangling:
                out.append(fail("C4", f"engine.evaluation {pid}: system_id {sid} is not a core.system"))
            else:
                out.append(fail("C4", f"engine.evaluation {pid}: system {sid} belongs to another project "
                                      f"({owner}) than its engine project's ({project})"))
    return out


def _reports_follow_their_layout(cl: Cluster) -> list[Finding]:
    rows = cl.rows(cl.platform_db, """
        SELECT g.id::text, g.layout_id::text, l.id IS NULL, g.project_id::text, g.system_id::text,
               l.project_id::text, l.system_id::text
          FROM report_composer.generated_report g
          JOIN core.system s ON s.pid = g.system_id
          LEFT JOIN report_composer.layout l ON l.id = g.layout_id
         WHERE l.id IS NULL OR l.project_id <> g.project_id OR l.system_id <> g.system_id
         ORDER BY 1""")
    return [fail("C4", f"report_composer.generated_report {rid}: layout_id {lid} is not a report_composer.layout")
            if missing else
            fail("C4", f"report_composer.generated_report {rid}: project {gp} system {gs}, but its layout {lid} "
                       f"is of project {lp} system {ls}")
            for rid, lid, missing, gp, gs, lp, ls in rows]


def _answers(cl: Cluster) -> list[Finding]:
    """controls.submission_answer.system_version_pid, in each project database, is a version of
    THAT project. Orphan databases are C1's."""
    owner = dict(cl.rows(cl.platform_db, "SELECT pid::text, project_id::text FROM core.system"))
    out = []
    projects = core_projects(cl)
    for db in project_databases(cl):
        if db not in projects or not cl.exists(db, "controls.submission_answer"):
            continue
        pid = projects[db][0]
        for aid, sv in cl.rows(db, "SELECT id, system_version_pid::text FROM controls.submission_answer"
                                   " WHERE system_version_pid IS NOT NULL ORDER BY id"):
            if sv not in owner:
                out.append(fail("C4", f"{db} controls.submission_answer {aid}: system_version_pid {sv} "
                                      "is not a core.system"))
            elif owner[sv] != pid:
                out.append(fail("C4", f"{db} controls.submission_answer {aid}: version {sv} belongs to "
                                      f"another project ({owner[sv]}) than the database's ({pid})"))
    return out


def c4_references(cl: Cluster) -> list[Finding]:
    """Every reference into core.project and core.system resolves, and to the right project."""
    out = _engine(cl)
    for table in PAIRED:
        if cl.exists(cl.platform_db, table):
            out += _paired(cl, table)
    if cl.exists(cl.platform_db, "report_composer.generated_report"):
        out += _reports_follow_their_layout(cl)
    return out + _answers(cl)


# ── C5 ───────────────────────────────────────────────────────────────────────

def _columns(cl: Cluster, db: str, where: str) -> list[tuple[str, str, str]]:
    """(schema, table, column) of information_schema.columns matching `where`."""
    return cl.rows(db, "SELECT table_schema, table_name, column_name FROM information_schema.columns"
                       f" WHERE {where} ORDER BY 1, 2, 3")


def _subjects(cl: Cluster) -> dict[str, set[str]]:
    """Every stored Keycloak subject, to where it was found (table.column)."""
    found: dict[str, set[str]] = {}

    def collect(db: str, schema: str, table: str, column: str, label: str) -> None:
        for (sub,) in cl.rows(db, f'SELECT DISTINCT "{column}"::text FROM "{schema}"."{table}"'
                                  f' WHERE "{column}" IS NOT NULL AND "{column}"::text <> \'\''):
            found.setdefault(sub, set()).add(label)

    db = cl.platform_db
    if cl.exists(db, "core.project_member"):
        collect(db, "core", "project_member", "subject", "core.project_member.subject")
    for schema, table, column in _columns(cl, db, "table_schema = 'report_composer' AND column_name LIKE '%\\_by'"
                                                  " AND table_name <> 'schema_migration'"):
        collect(db, schema, table, column, f"{schema}.{table}.{column}")
    if cl.superset_db in cl.databases():
        for schema, table, column in _columns(cl, cl.superset_db, "table_schema = 'public'"
                                              " AND table_name LIKE 'aisc\\_%' AND column_name LIKE '%\\_sub'"):
            collect(cl.superset_db, schema, table, column, f"{table}.{column}")
    return found


def c5_users(cl: Cluster) -> list[Finding]:
    """Every stored Keycloak subject is a user of the realm. Skipped, with a WARN saying so,
    when the Keycloak database cannot be read."""
    try:
        users = {r[0] for r in cl.rows(cl.keycloak_db, "SELECT u.id FROM user_entity u"
                                       " JOIN realm r ON r.id = u.realm_id WHERE r.name = %s", (cl.realm,))}
    except Exception as exc:
        reason = str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
        return [warn("C5", f"skipped: the {cl.keycloak_db} database cannot be read ({reason})")]
    return [warn("C5", f"subject {sub} in {', '.join(sorted(where))} is not a user of realm {cl.realm}")
            for sub, where in sorted(_subjects(cl).items()) if sub not in users]


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
    Check("C4", "references resolve", "every reference into core.project and core.system resolves",
          c4_references),
    Check("C5", "users resolve", "every stored subject is a Keycloak user", c5_users),
]
ALL_CHECKS = DATA_CHECKS
