"""The checks, C1 to C8. Each takes a Cluster and returns a list of findings; an empty list
means the check passed. Only SELECTs, on read-only connections (cluster.py)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .cluster import Cluster
from .findings import Finding, fail, warn

ROOT = Path(__file__).resolve().parents[2]
PROJECT_TEMPLATE = ROOT / "platform/project-template"
CONTROLS_MIGRATIONS = ROOT / "apps/controls/prisma/migrations"
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


# ── C6 ───────────────────────────────────────────────────────────────────────

def c6_stale_graph(cl: Cluster) -> list[Finding]:
    """An assessment's graph (control_objectives.graph, step 2) is still its card's current
    knowledge graph. The two digests are not comparable: qualification's comes from the
    ontology builder, control objectives' is the sha256 of the bytes it was served. So the
    comparison is by content, the sha256 of each side's jsonld."""
    db = cl.platform_db
    if not (cl.exists(db, "control_objectives.graph") and cl.exists(db, "qualification.knowledge_graph")):
        return []
    rows = cl.rows(db, """
        SELECT a.id, a.system_id::text, q.id, k.id IS NULL,
               encode(sha256(convert_to(g.jsonld, 'UTF8')), 'hex'),
               encode(sha256(convert_to(k.jsonld, 'UTF8')), 'hex'), g.uploaded_at, k.built_at
          FROM control_objectives.graph g
          JOIN control_objectives.project a ON a.id = g.project_id
          LEFT JOIN qualification.qualification q ON q.system_id = a.system_id
          LEFT JOIN qualification.knowledge_graph k ON k."qualificationId" = q.id
         ORDER BY a.id""")
    out = []
    for aid, sid, qid, missing, assessed, current, uploaded, built in rows:
        if missing:
            out.append(warn("C6", f"control_objectives project {aid} (system {sid}): its card "
                                  f"{qid or '(none)'} has no stored knowledge graph to compare with"))
        elif assessed != current:
            out.append(warn("C6", f"control_objectives project {aid} (system {sid}): its graph differs from "
                                  f"card {qid}'s current knowledge graph, compared by content (sha256 of jsonld "
                                  f"{assessed[:12]} vs {current[:12]}; uploaded {uploaded:%Y-%m-%d %H:%M}, "
                                  f"card graph built {built:%Y-%m-%d %H:%M})"))
    return out


# ── C7 ───────────────────────────────────────────────────────────────────────

def _behind(cl: Cluster, db: str, table: str, sql: str, wanted: list[str]) -> list[Finding]:
    if not cl.exists(db, table):
        return [fail("C7", f"{db}: {table} is missing, so none of its {len(wanted)} migrations is recorded")]
    have = {r[0] for r in cl.rows(db, sql)}
    lacking = [w for w in wanted if w not in have]
    return [fail("C7", f"{db}: {table} lacks {', '.join(lacking)}")] if lacking else []


def c7_migrations(cl: Cluster) -> list[Finding]:
    """Every project database has every platform/project-template/*.sql recorded in
    provision.template_migration, and every apps/controls/prisma/migrations migration finished
    (not rolled back) in controls._prisma_migrations."""
    templates = sorted(p.name for p in PROJECT_TEMPLATE.glob("*.sql"))
    controls = sorted(p.name for p in CONTROLS_MIGRATIONS.iterdir() if p.is_dir())
    out = []
    for db in project_databases(cl):
        out += _behind(cl, db, "provision.template_migration",
                       "SELECT name FROM provision.template_migration", templates)
        out += _behind(cl, db, "controls._prisma_migrations",
                       "SELECT migration_name FROM controls._prisma_migrations"
                       " WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL", controls)
    return out


# ── C8 ───────────────────────────────────────────────────────────────────────

#: Schemas of the platform database that follow the convention. engine is frozen and the
#: catalogue out of scope, so neither is here.
LINTED_PLATFORM_SCHEMAS = ("core", "qualification", "control_objectives", "report_composer")
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


def c8_naming(cl: Cluster) -> list[Finding]:
    """snake_case columns and timestamptz, in the schemas that are not frozen: core,
    qualification, control_objectives, report_composer, each project database's controls, and
    superset's aisc_* tables. Not engine (frozen), not the catalogue, not migration trackers."""
    schemas = ", ".join(f"'{s}'" for s in LINTED_PLATFORM_SCHEMAS)
    out = _lint(cl, cl.platform_db, f"c.table_schema IN ({schemas})", cl.platform_db)
    for db in project_databases(cl):
        out += _lint(cl, db, "c.table_schema = 'controls'", db)
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
    Check("C4", "references resolve", "every reference into core.project and core.system resolves",
          c4_references),
    Check("C5", "users resolve", "every stored subject is a Keycloak user", c5_users),
    Check("C6", "stale step-2 graph", "every assessment's graph is its card's current knowledge graph",
          c6_stale_graph),
    Check("C7", "project database migrations", "no project database is behind on its migrations",
          c7_migrations),
]
#: C8 is about the schemas, not the data: the clean data bed still has the real schemas' names.
ALL_CHECKS = DATA_CHECKS + [
    Check("C8", "naming and types", "every column is snake_case and every timestamp has a time zone",
          c8_naming),
]
