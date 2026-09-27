"""The checks, C1 to C8. Each takes a Cluster and returns a list of findings; an empty list
means the check passed. Only SELECTs, on read-only connections (cluster.py).

Isolation (2026-09-25, 01-specs.md I16.6): every module's tables and the card versions
(project.system) live in the project's own database `project_<hex>`; `platform` keeps only
core.project, core.project_member, core.schema_migration, the catalogue and the two libraries. So
C3, C4, C6 and C7 run per project database, and a reference that crosses projects cannot exist
(foreign keys); what can still go wrong is a pid that does not resolve in its own database."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import heads
from .cluster import Cluster
from .findings import Finding, fail, warn

ROOT = Path(__file__).resolve().parents[2]
PROJECT_TEMPLATE = heads.PROJECT_TEMPLATE
CONTROLS_MIGRATIONS = heads.CONTROLS_MIGRATIONS
LIBRARY_MIGRATIONS = ROOT / "apps/report-composer/migrations/library"
FORM_LIBRARY_MIGRATIONS = ROOT / "apps/qualification/prisma/library/migrations"
PROJECT_DB = re.compile(r"^project_[0-9a-f]{32}$")


def project_databases(cl: Cluster) -> list[str]:
    return [d for d in cl.databases() if PROJECT_DB.match(d)]


def core_projects(cl: Cluster) -> dict[str, tuple[str, str]]:
    """Every core.project: the database name it should have, to (pid, slug)."""
    rows = cl.rows(cl.platform_db, "SELECT pid::text, slug FROM core.project ORDER BY slug")
    return {"project_" + pid.replace("-", ""): (pid, slug) for pid, slug in rows}


def _dbs(cl: Cluster) -> list[tuple[str, str, str]]:
    """(database, pid, slug) of every project database that has its core.project row, by name.
    A database without one is an orphan, which is C1's to report."""
    projects = core_projects(cl)
    return [(db, *projects[db]) for db in sorted(project_databases(cl)) if db in projects]


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
#: I1.3: what stays in `platform`.
KNOWN_PLATFORM_SCHEMAS = {"core", "catalogue", "form_library", "report_library", "public"}
#: The module schemas the cutover retires (C9) and stage 7 drops (I15.2).
RETIRED_PLATFORM_SCHEMAS = {"engine", "qualification", "control_objectives", "report_composer"}
#: I1.3: core's tables after the drop step.
CORE_TABLES = {"project", "project_member", "schema_migration"}


def out_of_scope(name: str) -> bool:
    """The catalogue is not this check's business, wherever it lives."""
    return "catalogue" in name.lower()


def c2_unknown_databases_and_schemas(cl: Cluster) -> list[Finding]:
    """No database, and no schema of the platform database, outside the known list. A retired
    module schema, or a core table other than the three, is a WARN until the stage-7 drop."""
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
    for (s,) in schemas:
        if s in KNOWN_PLATFORM_SCHEMAS or out_of_scope(s):
            continue
        if s in RETIRED_PLATFORM_SCHEMAS:
            out.append(warn("C2", f"schema {s} in {cl.platform_db} is retired, pending the stage-7 drop"))
        else:
            out.append(fail("C2", f"schema {s} in {cl.platform_db} is not a known schema"))
    for (t,) in cl.rows(cl.platform_db, "SELECT c.relname FROM pg_class c"
                        " WHERE c.relnamespace = 'core'::regnamespace AND c.relkind IN ('r', 'p') ORDER BY 1"):
        if t not in CORE_TABLES:
            out.append(warn("C2", f"table core.{t} in {cl.platform_db} is not one of core's three tables,"
                                  " pending the stage-7 drop"))
    return out


# ── C3 ───────────────────────────────────────────────────────────────────────

#: qualification.qualification column, the project.system column it repeats
CARD_FIELDS = (("systemName", "name"), ("systemVersion", "version"), ("company", "provider"))
_ASSESSMENT_NAME = "s.name || CASE WHEN coalesce(s.version, '') <> '' THEN ' ' || s.version ELSE '' END"


def c3_system_identity(cl: Cluster) -> list[Finding]:
    """In each project database, a card version's name, version and provider read the same in
    project.system, qualification and control objectives. A NULL version or provider is the card's
    empty string; an assessment is named "<name> <version>", or "<name>" without a version."""
    out = []
    for db, _pid, slug in _dbs(cl):
        if not cl.exists(db, "project.system"):
            continue
        if cl.exists(db, "qualification.qualification"):
            rows = cl.rows(db, """
                SELECT s.pid::text, s.number, q.id, q."systemName", s.name, q."systemVersion",
                       coalesce(s.version, ''), q.company, coalesce(s.provider, '')
                  FROM qualification.qualification q JOIN project.system s ON s.pid = q.system_id
                 ORDER BY s.number, q.id""")
            for spid, number, qid, *values in rows:
                for i, (qcol, scol) in enumerate(CARD_FIELDS):
                    card, version = values[2 * i], values[2 * i + 1]
                    if card != version:
                        out.append(fail("C3", f"{db} ({slug}) system {spid} v{number}: qualification {qid} "
                                              f"{qcol} is '{card}', project.system {scol} is '{version}'"))
        if cl.exists(db, "control_objectives.project"):
            rows = cl.rows(db, f"""
                SELECT s.pid::text, s.number, a.id, a.name, {_ASSESSMENT_NAME}
                  FROM control_objectives.project a JOIN project.system s ON s.pid = a.system_id
                 WHERE a.name IS DISTINCT FROM {_ASSESSMENT_NAME}
                 ORDER BY s.number, a.id""")
            out += [fail("C3", f"{db} ({slug}) system {spid} v{number}: control_objectives project {aid} is "
                               f"named '{name}', project.system says '{want}'")
                    for spid, number, aid, name, want in rows]
    return out


# ── C4 ───────────────────────────────────────────────────────────────────────

#: (table, id column, version column): every module row that names a card version of its database.
STAMPED = (("qualification.qualification", "id", "system_id"),
           ("control_objectives.project", "id", "system_id"),
           ("report_composer.layout", "id", "system_id"),
           ("report_composer.generated_report", "id", "system_id"),
           ("engine.evaluation", "pid", "system_id"),
           ("controls.submission_answer", "id", "system_version_pid"))


def _dangling(cl: Cluster, db: str, table: str, key: str, column: str) -> list[Finding]:
    rows = cl.rows(db, f"""
        SELECT t.{key}::text, t.{column}::text FROM {table} t
          LEFT JOIN project.system s ON s.pid = t.{column}
         WHERE t.{column} IS NOT NULL AND s.pid IS NULL ORDER BY 1""")
    return [fail("C4", f"{db} {table} {rid}: {column} {sid} is not a project.system of this database")
            for rid, sid in rows]


def _answer_numbers(cl: Cluster, db: str) -> list[Finding]:
    rows = cl.rows(db, """
        SELECT a.id, a.system_version_pid::text, a.system_version_number, s.number
          FROM controls.submission_answer a JOIN project.system s ON s.pid = a.system_version_pid
         WHERE a.system_version_number IS DISTINCT FROM s.number ORDER BY 1""")
    return [fail("C4", f"{db} controls.submission_answer {aid}: system_version_number {got} but version "
                       f"{sv} is number {want}") for aid, sv, got, want in rows]


def _reports_follow_their_layout(cl: Cluster, db: str) -> list[Finding]:
    rows = cl.rows(db, """
        SELECT g.id::text, g.layout_id::text, l.id IS NULL, g.system_id::text, l.system_id::text
          FROM report_composer.generated_report g
          JOIN project.system s ON s.pid = g.system_id
          LEFT JOIN report_composer.layout l ON l.id = g.layout_id
         WHERE l.id IS NULL OR l.system_id IS DISTINCT FROM g.system_id
         ORDER BY 1""")
    return [fail("C4", f"{db} report_composer.generated_report {rid}: layout_id {lid} is not a "
                       "report_composer.layout of this database") if missing else
            fail("C4", f"{db} report_composer.generated_report {rid}: system {gs}, but its layout {lid} "
                       f"is of system {ls}")
            for rid, lid, missing, gs, ls in rows]


def _engine_projects(cl: Cluster, db: str, pid: str) -> list[Finding]:
    out = []
    for epid, name, project in cl.rows(db, """
            SELECT e.pid::text, e.name, e.project_id::text FROM engine.project e
             WHERE e.project_id IS DISTINCT FROM %s::uuid ORDER BY e.id""", (pid,)):
        if project is None:
            out.append(warn("C4", f"{db} engine.project {epid} ({name}) has no platform project (project_id is NULL)"))
        else:
            out.append(fail("C4", f"{db} engine.project {epid} ({name}): project_id {project} is not "
                                  f"this database's project {pid}"))
    return out


def _card_components(cl: Cluster, db: str) -> list[Finding]:
    """I16.6: a card's component is one of the engine's components of the same database."""
    rows = cl.rows(db, """
        SELECT c.id, c.component_pid::text FROM qualification.card_component c
         WHERE NOT EXISTS (SELECT 1 FROM engine.ai_component a WHERE a.pid = c.component_pid)
         ORDER BY 1""")
    return [fail("C4", f"{db} qualification.card_component {cid}: component_pid {cp} is not an "
                       "engine.ai_component of this database") for cid, cp in rows]


def c4_references(cl: Cluster) -> list[Finding]:
    """In each project database, every card-version pid resolves in its project.system, a stamped
    answer carries its version's number, a report follows its layout, the engine's project is this
    database's, and every card component is an engine component."""
    out = []
    for db, pid, _slug in _dbs(cl):
        has_system = cl.exists(db, "project.system")
        for table, key, column in STAMPED:
            if has_system and cl.exists(db, table):
                out += _dangling(cl, db, table, key, column)
        if has_system and cl.exists(db, "controls.submission_answer"):
            out += _answer_numbers(cl, db)
        if has_system and cl.exists(db, "report_composer.generated_report"):
            out += _reports_follow_their_layout(cl, db)
        if cl.exists(db, "engine.project"):
            out += _engine_projects(cl, db, pid)
        if cl.exists(db, "qualification.card_component") and cl.exists(db, "engine.ai_component"):
            out += _card_components(cl, db)
    return out


# ── C5 ───────────────────────────────────────────────────────────────────────

def _columns(cl: Cluster, db: str, where: str) -> list[tuple[str, str, str]]:
    """(schema, table, column) of information_schema.columns matching `where`."""
    return cl.rows(db, "SELECT table_schema, table_name, column_name FROM information_schema.columns"
                       f" WHERE {where} ORDER BY 1, 2, 3")


def _subjects(cl: Cluster) -> dict[str, set[str]]:
    """Every stored Keycloak subject, to where it was found ([database] table.column)."""
    found: dict[str, set[str]] = {}

    def collect(db: str, schema: str, table: str, column: str, label: str) -> None:
        for (sub,) in cl.rows(db, f'SELECT DISTINCT "{column}"::text FROM "{schema}"."{table}"'
                                  f' WHERE "{column}" IS NOT NULL AND "{column}"::text <> \'\''):
            found.setdefault(sub, set()).add(label)

    db = cl.platform_db
    if cl.exists(db, "core.project_member"):
        collect(db, "core", "project_member", "subject", "core.project_member.subject")
    for pdb, _pid, _slug in _dbs(cl):
        for schema, table, column in _columns(cl, pdb, "table_schema = 'report_composer'"
                                              " AND column_name LIKE '%\\_by' AND table_name <> 'schema_migration'"):
            collect(pdb, schema, table, column, f"{pdb} {schema}.{table}.{column}")
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


# ── C6 ───────────────────────────────────────────────────────────────────────

def c6_stale_graph(cl: Cluster) -> list[Finding]:
    """In each project database, an assessment's graph (control_objectives.graph, step 2) is
    still its card's current knowledge graph. The two digests are not comparable: qualification's
    comes from the ontology builder, control objectives' is the sha256 of the bytes it was served.
    So the comparison is by content, the sha256 of each side's jsonld."""
    out = []
    for db, _pid, _slug in _dbs(cl):
        if not (cl.exists(db, "control_objectives.graph") and cl.exists(db, "qualification.knowledge_graph")):
            continue
        rows = cl.rows(db, """
            SELECT a.id, a.system_id::text, q.id, k.id IS NULL,
                   encode(sha256(convert_to(g.jsonld, 'UTF8')), 'hex'),
                   encode(sha256(convert_to(k.jsonld, 'UTF8')), 'hex'), g.uploaded_at, k.built_at
              FROM control_objectives.graph g
              JOIN control_objectives.project a ON a.id = g.project_id
              LEFT JOIN qualification.qualification q ON q.system_id = a.system_id
              LEFT JOIN qualification.knowledge_graph k ON k."qualificationId" = q.id
             ORDER BY a.id""")
        for aid, sid, qid, missing, assessed, current, uploaded, built in rows:
            if missing:
                out.append(warn("C6", f"{db} control_objectives project {aid} (system {sid}): its card "
                                      f"{qid or '(none)'} has no stored knowledge graph to compare with"))
            elif assessed != current:
                out.append(warn("C6", f"{db} control_objectives project {aid} (system {sid}): its graph differs "
                                      f"from card {qid}'s current knowledge graph, compared by content (sha256 of "
                                      f"jsonld {assessed[:12]} vs {current[:12]}; uploaded "
                                      f"{uploaded:%Y-%m-%d %H:%M}, card graph built {built:%Y-%m-%d %H:%M})"))
    return out


# ── C7 ───────────────────────────────────────────────────────────────────────

def _behind(cl: Cluster, db: str, tracker: heads.Tracker) -> list[Finding]:
    if not cl.exists(db, tracker.table):
        return [fail("C7", f"{db}: {tracker.table} is missing, so none of its {len(tracker.wanted)} "
                           "migrations is recorded")]
    applied = {r[0] for r in cl.rows(db, tracker.sql)}
    lacking = heads.behind(tracker, applied)
    out = [fail("C7", f"{db}: {tracker.table} lacks {', '.join(lacking)}")] if lacking else []
    stray = heads.extra(tracker, applied)
    if stray:
        out.append(fail("C7", f"{db}: {tracker.table} is at {', '.join(stray)}, not at the head"))
    return out


def _library_trackers() -> list[heads.Tracker]:
    out = []
    if LIBRARY_MIGRATIONS.is_dir():
        out.append(heads.Tracker("report_library", "report_library.schema_migration",
                                 "SELECT name FROM report_library.schema_migration",
                                 tuple(sorted(p.name for p in LIBRARY_MIGRATIONS.glob("*.sql")))))
    if FORM_LIBRARY_MIGRATIONS.is_dir():
        out.append(heads.Tracker("form_library", "form_library._prisma_migrations",
                                 "SELECT migration_name FROM form_library._prisma_migrations"
                                 " WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL",
                                 tuple(sorted(p.name for p in FORM_LIBRARY_MIGRATIONS.iterdir() if p.is_dir()))))
    return out


def c7_migrations(cl: Cluster) -> list[Finding]:
    """Every project database is at the head of every history it has: the platform template
    (provision.template_migration), qualification and controls (Prisma, finished and not rolled
    back), control objectives (alembic), the engine (Django) and the report composer; and in
    `platform`, the two libraries when this tree has their migrations."""
    out = []
    trackers = heads.trackers()
    for db in project_databases(cl):
        for tracker in trackers:
            out += _behind(cl, db, tracker)
    for tracker in _library_trackers():
        if cl.rows(cl.platform_db, "SELECT to_regnamespace(%s) IS NOT NULL", (tracker.table.split(".")[0],))[0][0]:
            out += _behind(cl, cl.platform_db, tracker)
    return out


# ── C8 ───────────────────────────────────────────────────────────────────────

#: Schemas of the platform database that follow the convention (the catalogue is out of scope).
LINTED_PLATFORM_SCHEMAS = ("core", "form_library", "report_library")
#: Schemas of a project database that follow it. engine is frozen, so it is not here.
LINTED_PROJECT_SCHEMAS = ("project", "qualification", "control_objectives", "report_composer", "controls")
#: The migration tools' own tables: their columns are the tool's, not ours.
MIGRATION_TRACKERS = ("schema_migration", "template_migration", "_prisma_migrations", "alembic_version")
SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


def _lint(cl: Cluster, db: str, where: str, label: str) -> list[Finding]:
    rows = cl.rows(db, f"""
        SELECT c.table_schema, c.table_name, c.column_name, c.data_type
          FROM information_schema.columns c
          JOIN information_schema.tables t
            ON t.table_schema = c.table_schema AND t.table_name = c.table_name
         WHERE t.table_type = 'BASE TABLE' AND ({where})
         ORDER BY c.table_schema, c.table_name, c.ordinal_position""")
    names: dict[str, list[str]] = {}
    naive: dict[str, list[str]] = {}
    for schema, table, column, dtype in rows:
        if table in MIGRATION_TRACKERS or out_of_scope(column):
            continue
        where_ = f"{schema}.{table}" if schema != "public" else table
        if not SNAKE.match(column):
            names.setdefault(where_, []).append(column)
        if dtype == "timestamp without time zone":
            naive.setdefault(where_, []).append(column)
    return ([warn("C8", f"{label} {t}: columns not snake_case: {', '.join(c)}") for t, c in names.items()]
            + [warn("C8", f"{label} {t}: timestamp without time zone: {', '.join(c)}") for t, c in naive.items()])


def _in(schemas: tuple[str, ...]) -> str:
    return "c.table_schema IN (" + ", ".join(f"'{s}'" for s in schemas) + ")"


def c8_naming(cl: Cluster) -> list[Finding]:
    """snake_case columns and timestamptz, in the schemas that are not frozen: core and the two
    libraries of `platform`; project, qualification, control_objectives, report_composer and
    controls of each project database; superset's aisc_* tables. Not engine (frozen), not the
    catalogue, not migration trackers. Each finding names its database."""
    out = _lint(cl, cl.platform_db, _in(LINTED_PLATFORM_SCHEMAS), cl.platform_db)
    for db in project_databases(cl):
        out += _lint(cl, db, _in(LINTED_PROJECT_SCHEMAS), db)
    if cl.superset_db in cl.databases():
        out += _lint(cl, cl.superset_db, "c.table_schema = 'public' AND c.table_name LIKE 'aisc\\_%'",
                     cl.superset_db)
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
    Check("C4", "references resolve", "every card version, stamp and component resolves in its own database",
          c4_references),
    Check("C5", "users resolve", "every stored subject is a Keycloak user", c5_users),
    Check("C6", "stale step-2 graph", "every assessment's graph is its card's current knowledge graph",
          c6_stale_graph),
    Check("C7", "migrations at head", "no database is behind on any of its migrations",
          c7_migrations),
]
#: C8 is about the schemas, not the data: the clean data bed still has the real schemas' names.
ALL_CHECKS = DATA_CHECKS + [
    Check("C8", "naming and types", "every column is snake_case and every timestamp has a time zone",
          c8_naming),
]
