"""Checks made before anything is written (01-specs.md I12.6, I13.4).

Every function returns a list of refusals (dicts of the report); none writes.
The head lists are copied here, not imported from the tests.
"""
from __future__ import annotations

from psycopg import sql

from .catalog import DROPPED_COLUMNS, Table

OLD_QUALIFICATION = [
    "20260430105826_add_qualification",
    "20260430112359_add_system_card",
    "20260430115050_add_taxonomy_and_pdf",
    "20260430120000_multi_tags",
    "20260430140000_keycloak_drop_passwordhash",
    "20260602000000_drop_auth_open_app",
    "20260910120000_add_risks_and_airo_fields",
    "20260910180000_add_ontology_columns",
    "20260914150253_add_ontology_versions",
    "20260914151848_knowledge_graph_per_system",
    "20260921233000_qualification_of_a_project_and_a_system",
    "20260922100000_the_links_are_named_project_id_and_system_id",
    "20260922110000_one_naming_convention",
    "20260923180000_one_ai_card_per_system_version",
    "20260923210000_card_versions_point_at_core_system",
    "20260924120000_a_card_is_of_a_version_of_its_project",
]
FORMS_MIGRATIONS = ["20260925090000_forms_are_data", "20260925120000_the_default_form_is_fixed"]
OLD_ALEMBIC = "7c3e5a9b1d24"
# The OLD chain on purpose: an old install (the source) was migrated by the engine of before the
# adapt plan (2026-09-28), whose 0024 dropped the login tables. Today's chain ends at 0021.
OLD_DJANGO_HEAD = "0024_no_login_of_its_own"
OLD_COMPOSER = [
    "0001_report_composer.sql", "0002_templates_are_looks.sql",
    "0003_a_report_points_at_its_project_and_version.sql", "0004_a_version_of_its_project.sql",
    "0005_presets_and_document_settings.sql",
]
OLD_CORE = [
    "0001_project_membership.sql", "0002_one_ai_system_per_project.sql",
    "0003_card_versions_in_core_system.sql", "0004_card_version_of_its_project.sql",
]
NEW_QUALIFICATION_BASELINE = "20260925000000_project_database"
NEW_ALEMBIC = "20260926000000_project_database"
# Today's chain (Sean's 0001..0014, ours 0015..0021) ends at the mode marker: only a target
# with its last migration is at the new head (0020, the project database layout, was 0025 before
# the adapt plan of 2026-09-28; a target at 0020 without 0021 stopped halfway).
NEW_DJANGO = "0021_engine_deployment_marker"
NEW_COMPOSER = "0001_project_database.sql"
CONTROLS_HEAD = [
    "20260923120000_project_database",
    "20260923210000_answers_carry_the_system_version",
    "20260923210100_dashboard_reads_controls",
]
#: Roles whose sessions must be gone before a copy (I12.6, I13.4).
SESSION_ROLES = ("platform_rw", "report_ro", "dashboard_ro")


def refusal(reason: str, *, table: str | None = None, project: str | None = None,
            projects=None, keys=None, detail: str | None = None) -> dict:
    r = {"reason": reason, "table": table, "project": project,
         "projects": sorted(projects) if projects else ([project] if project else []),
         "keys": list(keys or [])}
    if detail:
        r["detail"] = detail
    return r


def _exists(conn, table: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()[0]


def _names(conn, table: str, column: str, finished: bool = False) -> set[str] | None:
    """The names in a bookkeeping table; with `finished`, only finished, not rolled back
    Prisma rows. None when the table is missing."""
    if not _exists(conn, table):
        return None
    q = sql.SQL("SELECT {} FROM {}").format(sql.Identifier(column), sql.Identifier(*table.split(".")))
    if finished:
        q = q + sql.SQL(" WHERE finished_at IS NOT NULL AND rolled_back_at IS NULL")
    return {r[0] for r in conn.execute(q).fetchall()}


def source_has_forms(conn) -> bool:
    return _exists(conn, "qualification.form")


def old_heads(conn) -> list[dict]:
    """The source is at the pre-isolation heads of this branch (S-D3: forms optional)."""
    out = []

    def need(what: str, have: set[str] | None, names) -> None:
        missing = sorted(set(names) - (have or set()))
        if have is None or missing:
            out.append(refusal("source not at old head", table=what,
                               detail=f"{len(missing) if have is not None else 'table'} missing"))

    quals = OLD_QUALIFICATION + (FORMS_MIGRATIONS if source_has_forms(conn) else [])
    need("qualification._prisma_migrations",
         _names(conn, "qualification._prisma_migrations", "migration_name", finished=True), quals)
    alembic = _names(conn, "control_objectives.alembic_version", "version_num")
    if alembic != {OLD_ALEMBIC}:
        out.append(refusal("source not at old head", table="control_objectives.alembic_version"))
    need("engine.django_migrations", _names(conn, "engine.django_migrations", "name"), [OLD_DJANGO_HEAD])
    need("report_composer.schema_migration", _names(conn, "report_composer.schema_migration", "name"),
         OLD_COMPOSER)
    need("core.schema_migration", _names(conn, "core.schema_migration", "name"), OLD_CORE)
    return out


def new_heads(conn, pid: str, forms: bool, template_files: list[str]) -> list[dict]:
    """A project database is at the new heads of every module and has every template file."""
    out = []

    def need(what: str, have: set[str] | None, names) -> None:
        if have is None or set(names) - have:
            out.append(refusal("target not at new head", table=what, project=pid))

    need("qualification._prisma_migrations",
         _names(conn, "qualification._prisma_migrations", "migration_name", finished=True),
         [NEW_QUALIFICATION_BASELINE] + (FORMS_MIGRATIONS if forms else []))
    need("control_objectives.alembic_version",
         _names(conn, "control_objectives.alembic_version", "version_num"), [NEW_ALEMBIC])
    need("engine.django_migrations", _names(conn, "engine.django_migrations", "name"), [NEW_DJANGO])
    need("report_composer.schema_migration",
         _names(conn, "report_composer.schema_migration", "name"), [NEW_COMPOSER])
    need("controls._prisma_migrations",
         _names(conn, "controls._prisma_migrations", "migration_name", finished=True), CONTROLS_HEAD)
    applied = _names(conn, "provision.template_migration", "name") or set()
    missing = sorted(set(template_files) - applied)
    if missing:
        out.append(refusal("missing template", table="provision.template_migration", project=pid,
                           detail=", ".join(missing)))
    return out


def column_coverage(source: Table, target: Table | None, target_name: str, pid: str | None) -> list[dict]:
    """Every source column (but the allowed dropped ones) exists in the target with the same
    type; every target-only column has a default or is nullable."""
    if target is None:
        return [refusal("column coverage", table=source.name, project=pid,
                        detail=f"{target_name} missing")]
    out = []
    allowed = DROPPED_COLUMNS.get(source.name, set())
    for c in source.columns:
        if c.name in allowed:
            continue
        t = target.column(c.name)
        if t is None:
            out.append(refusal("column coverage", table=source.name, project=pid,
                               detail=f"column {c.name} missing in {target_name}"))
        elif t.type != c.type:
            out.append(refusal("column coverage", table=source.name, project=pid,
                               detail=f"column {c.name} is {t.type} in {target_name}, {c.type} in the source"))
    src = set(source.column_names)
    for t in target.columns:
        if t.name not in src and t.not_null and not t.has_default and not t.generated:
            out.append(refusal("column coverage", table=source.name, project=pid,
                               detail=f"column {t.name} of {target_name} is NOT NULL without a default"))
    for c in source.pk:
        if target.column(c) is None:
            out.append(refusal("column coverage", table=source.name, project=pid,
                               detail=f"key column {c} missing in {target_name}"))
    return out


def active_sessions(conn, databases: list[str], own_pids: list[int]) -> list[dict]:
    """Sessions of platform_rw, of a module's *_rw role, or of a reader, on the source or a target."""
    rows = conn.execute(
        "SELECT datname, count(*) FROM pg_stat_activity"
        " WHERE datname = ANY(%s) AND NOT (pid = ANY(%s))"
        "   AND (usename = ANY(%s) OR usename LIKE '%%\\_rw')"
        " GROUP BY datname ORDER BY datname",
        (databases, own_pids, list(SESSION_ROLES))).fetchall()
    return [refusal("active sessions", detail=f"{n} session(s) on {db}") for db, n in rows]
