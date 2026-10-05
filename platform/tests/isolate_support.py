"""A synthetic old-layout platform and its project databases, for tests/test_isolate.py.

A *world* is:

- a source database `isosrc_<hex>` on the throwaway cluster, shaped exactly like the live
  `platform` at its old-layout heads: scripts/tests/fixtures/isolation/live_shape.sql (schema-only
  dump of the live moving schemas and core) plus report_composer 0003..0005 (the cutover runs
  them before the copy), plus the two install-wide libraries the new layout keeps in `platform`
  (`form_library.*` and `report_library.preset`);
- two projects A < B (pid order) with rows in every moving schema, chosen to exercise every copy
  rule: a self-reference (form_question.copied_from_id, ai_component.source_dataset_id), an
  identifying child (engine.aisc_backend_derived, engine.aisc_backend_direct, form_version_question), shared "needed" rows
  (the default form, metric 1), a historical row a trigger would refuse (answers of card version 1),
  unowned rows (engine project with no platform project, its plugin, metric 4, metric category 2),
  sequences whose value differs from max(id), and value types that break naive text copies
  (double precision, bytea, jsonb, arrays, timestamps);
- one target database per project made by `platform_service.projectdb.provision` (the real
  template), into which this module then creates the module tables at their *new* heads.

The target module tables are created here rather than by the modules' own migrations, so the
tests do not depend on every module's migration files. Their shape is derived from the same live
shape: project_id dropped from the five tables and from core.system, core.system becomes
project.system, foreign keys to core.project dropped, foreign keys to core.system re-pointed at
project.system, composite keys dropped; the bookkeeping tables get the new head names. Everything
is IF NOT EXISTS / ON CONFLICT DO NOTHING, so the helper only fills what the real template files
did not make.

Every value that must never appear in the tool's output carries MARK (a per-world random token).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.types.json import Jsonb

from platform_service import projectdb

REPO = Path(__file__).resolve().parents[2]
LIVE_SHAPE = REPO / "scripts" / "tests" / "fixtures" / "isolation" / "live_shape.sql"
COMPOSER_MIGRATIONS = REPO / "apps" / "report-composer" / "pre_isolation_migrations"
PLATFORM_DIR = REPO / "platform"

SUPERUSER_DSN = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")
PLATFORM_RW_DSN = os.environ.get("PLATFORM_TEST_DATABASE_URL")

MOVING_SCHEMAS = ("qualification", "control_objectives", "engine", "report_composer")
#: The tables whose platform-project column is dropped (core.system loses it too).
DROPPED_PROJECT_ID = {
    "qualification.qualification",
    "control_objectives.project",
    "report_composer.layout",
    "report_composer.template",
    "report_composer.generated_report",
}
#: The tables that stay in `platform`: the only hand-written knowledge the tool may have.
STAYS_SHARED = {"core.project", "core.project_member", "core.schema_migration"}
BOOKKEEPING = {
    "qualification._prisma_migrations",
    "control_objectives.alembic_version",
    "engine.django_migrations",
    "engine.django_content_type",
    "report_composer.schema_migration",
}
FORM_TABLES = ("form", "form_version", "form_question", "form_version_question")

# Migration heads.
# Old layout: the pre-isolation migration histories, pinned here by name because the old
# qualification and alembic migration directories are gone from the repo.
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
OLD_DJANGO = [
    "0001_initial", "0002_evaluationplugin_evaluation_config",
    "0003_remove_evaluationplugin_evaluation_config_and_more",
    "0004_remove_dataset_plugin_remove_evaluation_dataset_and_more", "0005_artifact",
    "0006_plugin_package_name_plugin_version_and_more",
    "0007_alter_plugin_unique_together_plugin_display_name", "0008_remove_datashape_dataset_and_more",
    "0009_alter_measurement_dimensions", "0010_plugin_enabled",
    "0011_artifact_file_size_dataset_file_size_model_file_size", "0012_measurement_direction",
    "0013_projectsetting_pluginconfigsetting_and_more", "0014_plugin_catalogue_slug",
    "0015_evaluation_system_id_project_platform_project_id", "0016_one_project_per_platform_project",
    "0017_alter_project_platform_project_id", "0018_alter_artifact_table_alter_dataset_table_and_more",
    "0019_alter_derived_table_alter_direct_table", "0020_ai_system_and_project_config",
    "0021_ai_system_tables_lose_the_prefix", "0022_parts_belong_to_a_version_of_the_one_system",
    "0023_one_system_per_project_again", "0024_no_login_of_its_own",
]
OLD_COMPOSER = [
    "0001_report_composer.sql", "0002_templates_are_looks.sql",
    "0003_a_report_points_at_its_project_and_version.sql", "0004_a_version_of_its_project.sql",
    "0005_presets_and_document_settings.sql",
]
OLD_CORE = [
    "0001_project_membership.sql", "0002_one_ai_system_per_project.sql",
    "0003_card_versions_in_core_system.sql", "0004_card_version_of_its_project.sql",
]
# New layout: the heads a project database records after the copy.
NEW_QUALIFICATION_BASELINE = "20260925000000_project_database"
NEW_ALEMBIC = "20260926000000_project_database"
NEW_DJANGO = "0021_engine_deployment_marker"   # the last migration of the engine's chain
# What migrate_projects records in a project database: the engine's 0001..0014 (its master) and
# this branch's 0015..0021. OLD_DJANGO above is the old chain on purpose (the source, an old install).
NEW_DJANGO_CHAIN = [
    "0001_initial", "0002_evaluationplugin_evaluation_config",
    "0003_remove_evaluationplugin_evaluation_config_and_more",
    "0004_remove_dataset_plugin_remove_evaluation_dataset_and_more", "0005_artifact",
    "0006_plugin_package_name_plugin_version_and_more",
    "0007_alter_plugin_unique_together_plugin_display_name", "0008_remove_datashape_dataset_and_more",
    "0009_alter_measurement_dimensions", "0010_plugin_enabled",
    "0011_artifact_file_size_dataset_file_size_model_file_size", "0012_measurement_direction",
    "0013_projectsetting_pluginconfigsetting_and_more", "0014_ai_system_and_project_config_squashed",
    "0015_plugin_catalogue_slug", "0016_evaluation_system_id_project_platform_project_id",
    "0017_one_project_per_platform_project", "0018_alter_project_platform_project_id",
    "0019_no_login_of_its_own", "0020_the_database_is_the_project", "0021_engine_deployment_marker",
]
NEW_COMPOSER = "0001_project_database.sql"
CONTROLS_HEAD = [
    "20260923120000_project_database",
    "20260923210000_answers_carry_the_system_version",
    "20260923210100_dashboard_reads_controls",
]
NEW_TEMPLATE = [
    "0006_project_system.sql", "0007_qualification.sql", "0008_control_objectives.sql",
    "0009_engine.sql", "0010_report_composer.sql",
]

T0 = "2026-09-01 10:00:00+00"

#: The session settings the tool reads rows with, used by the tests' own checksums too.
ROW_TEXT_SETTINGS = (
    "SET TimeZone = 'UTC'; SET DateStyle = 'ISO'; SET extra_float_digits = 3; SET bytea_output = 'hex'"
)


def refuse_live(dsn: str) -> None:
    port = str(conninfo_to_dict(dsn).get("port", "5432"))
    if port == "5432":
        raise RuntimeError("refusing to run the isolate tests against port 5432 (live)")


def dsn_for(dbname: str) -> str:
    return make_conninfo(SUPERUSER_DSN, dbname=dbname)


def password_of(dsn: str) -> str:
    return str(conninfo_to_dict(dsn).get("password") or "")


# Splitting a pg_dump into statements.


def split_sql(text: str) -> list[str]:
    """Top-level statements of a SQL script: honours '...', "...", $tag$...$tag$ and -- comments."""
    out, buf, i, n = [], [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "-" and text.startswith("--", i):
            j = text.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if c in ("'", '"'):
            j = i + 1
            while j < n:
                if text[j] == c:
                    if j + 1 < n and text[j + 1] == c:
                        j += 2
                        continue
                    break
                j += 1
            buf.append(text[i : j + 1])
            i = j + 1
            continue
        if c == "$":
            m = re.match(r"\$[A-Za-z_]*\$", text[i:])
            if m:
                tag = m.group(0)
                j = text.find(tag, i + len(tag))
                j = n if j < 0 else j + len(tag)
                buf.append(text[i:j])
                i = j
                continue
        if c == ";":
            stmt = "".join(buf).strip()
            if stmt:
                out.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(c)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out


_SHARED_CORE = re.compile(r"core\.(project|project_member|schema_migration)\b")
_FORMS = re.compile(
    r"qualification\.form(_version_question|_version|_question)?\b|form_builtin_is_fixed|form_name_is_fixed"
    r"|form_question_identity_is_fixed|form_version_is_append_only|form_version_question_is_append_only"
)
_TABLE_OF = re.compile(
    r"(?:CREATE TABLE|ALTER TABLE ONLY|ALTER TABLE|\bON)\s+([a-z_]+\.[a-z_]+)", re.I
)


def table_of(stmt: str) -> str | None:
    m = _TABLE_OF.search(stmt)
    return m.group(1) if m else None


def drop_column(create_table: str, column: str) -> str:
    lines = create_table.split("\n")
    pat = re.compile(rf'^\s+"?{re.escape(column)}"?\s')
    for k, line in enumerate(lines):
        if pat.match(line):
            had_comma = line.rstrip().endswith(",")
            del lines[k]
            if not had_comma:
                for p in range(k - 1, -1, -1):
                    if lines[p].strip():
                        lines[p] = lines[p].rstrip().rstrip(",")
                        break
            return "\n".join(lines)
    raise AssertionError(f"column {column} not found in {create_table[:60]!r}")


def without_forms(stmts: list[str]) -> list[str]:
    """The old layout before the forms migrations (for the forms-absent world)."""
    out = []
    for s in stmts:
        if _FORMS.search(s):
            continue
        if table_of(s) == "qualification.qualification" and "form_version_id" in s:
            if s.lstrip().upper().startswith("CREATE TABLE"):
                s = drop_column(s, "form_version_id")
            else:
                continue
        out.append(s)
    return out


def _schemas_then_functions_first(stmts: list[str]) -> list[str]:
    """The fixture defines core.system_only_latest_changes() after the trigger that calls it."""
    rank = lambda s: 0 if s.startswith("CREATE SCHEMA") else 1 if re.match(r"CREATE (OR REPLACE )?FUNCTION", s) else 2
    return sorted(stmts, key=rank)  # sorted() is stable


def source_statements(forms: bool) -> list[str]:
    stmts = _schemas_then_functions_first(split_sql(LIVE_SHAPE.read_text()))
    for name in OLD_COMPOSER[2:]:
        stmts += split_sql((COMPOSER_MIGRATIONS / name).read_text())
    return stmts if forms else without_forms(stmts)


PROJECT_SYSTEM_DDL = """
CREATE SCHEMA IF NOT EXISTS project;
CREATE TABLE IF NOT EXISTS project.system (
    pid uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    number integer NOT NULL CHECK (number > 0) UNIQUE,
    name text NOT NULL,
    version text,
    provider text,
    description text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    created_by text
);
CREATE OR REPLACE FUNCTION project.system_only_latest_changes() RETURNS trigger LANGUAGE plpgsql AS $f$
BEGIN
  IF NEW.number <> OLD.number OR OLD.number < (SELECT max(number) FROM project.system) THEN
    RAISE EXCEPTION 'system version % is not the latest and cannot change', OLD.number;
  END IF;
  RETURN NEW;
END $f$;
DO $d$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'system_only_latest_changes'
                  AND tgrelid = 'project.system'::regclass) THEN
    CREATE TRIGGER system_only_latest_changes BEFORE UPDATE ON project.system
      FOR EACH ROW EXECUTE FUNCTION project.system_only_latest_changes();
  END IF;
END $d$;
"""

CARD_IS_LATEST = """CREATE OR REPLACE FUNCTION qualification.card_is_latest(version_pid uuid) RETURNS boolean
    LANGUAGE plpgsql STABLE
    AS $$
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM project.system s
     WHERE s.pid = version_pid AND s.number = (SELECT max(o.number) FROM project.system o));
END $$"""


def target_statements(forms: bool) -> list[str]:
    """Create the new-layout module tables of a project database."""
    out = []
    for s in source_statements(forms):
        if _SHARED_CORE.search(s) or s.startswith("COMMENT ON"):
            continue
        if s.startswith("CREATE FUNCTION qualification.card_is_latest"):
            out.append(CARD_IS_LATEST)
            continue
        if "core.system" in s:
            if re.search(r"REFERENCES core\.system\s*\(pid\)", s):
                s = re.sub(r"REFERENCES core\.system\s*\(pid\)", "REFERENCES project.system(pid)", s)
            else:
                continue
        t = table_of(s)
        if t in DROPPED_PROJECT_ID:
            if s.lstrip().upper().startswith("CREATE TABLE"):
                s = drop_column(s, "project_id")
            elif "project_id" in s:
                continue
        s = re.sub(r"^CREATE SCHEMA (\w+)$", r"CREATE SCHEMA IF NOT EXISTS \1", s)
        out.append(s)
    return out


def library_statements() -> list[str]:
    """Create form_library.* (the four form tables, their constraints and triggers) and
    report_library.preset (source_project_id without a foreign key)."""
    out = ["CREATE SCHEMA IF NOT EXISTS form_library"]
    for s in split_sql(LIVE_SHAPE.read_text()):
        if not _FORMS.search(s) or table_of(s) == "qualification.qualification":
            continue
        out.append(s.replace("qualification.", "form_library."))
    out += [
        "CREATE SCHEMA IF NOT EXISTS report_library",
        """CREATE TABLE report_library.preset (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name text NOT NULL UNIQUE,
            description text NOT NULL DEFAULT '',
            language text, toc text, numbering boolean,
            blocks jsonb NOT NULL,
            source_project_id uuid NULL,
            created_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now())""",
        "CREATE TABLE report_library.schema_migration (name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())",
        "INSERT INTO report_library.schema_migration (name) VALUES ('0001_presets.sql')",
    ]
    return out


# The world.


@dataclass
class World:
    tag: str
    source_db: str
    A: str
    B: str
    forms: bool
    mark: str
    ids: dict = field(default_factory=dict)

    @property
    def source_dsn(self) -> str:
        return dsn_for(self.source_db)

    def target_db(self, pid: str) -> str:
        return projectdb.database_name(pid)

    def target_dsn(self, pid: str) -> str:
        return dsn_for(self.target_db(pid))

    @property
    def pids(self) -> list[str]:
        return [self.A, self.B]

    def source(self, **kw) -> psycopg.Connection:
        return psycopg.connect(self.source_dsn, autocommit=True, **kw)

    def target(self, pid: str) -> psycopg.Connection:
        return psycopg.connect(self.target_dsn(pid), autocommit=True)


def _insert(conn, table: str, row: dict) -> None:
    cols = list(row)
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(*table.split(".")),
            sql.SQL(", ").join(sql.Identifier(c) for c in cols),
            sql.SQL(", ").join(sql.Placeholder() for _ in cols),
        ),
        [row[c] for c in cols],
    )


def default_form_rows() -> list[tuple[str, dict]]:
    """The seeded Annex IV default form (what the forms migrations put in every database)."""
    return [
        ("form", dict(id="annex-iv-default", name="Annex IV", description="", origin="builtin",
                      listed=True, created_at=T0)),
        ("form_question", dict(id="dq1", owner_form_id="annex-iv-default", scope="annex-iv",
                               local_id="q1", copied_from_id=None, created_at=T0)),
        ("form_question", dict(id="dq2", owner_form_id="annex-iv-default", scope="annex-iv",
                               local_id="q2", copied_from_id=None, created_at=T0)),
        ("form_version", dict(id="annex-iv-default-v1", form_id="annex-iv-default", number=1,
                              blocks=["description", "risks"], created_at=T0)),
        ("form_version_question", dict(form_version_id="annex-iv-default-v1", question_id="dq1",
                                       position=0, text="What does it do?", citation="",
                                       required=True, annex_point="1a", group_label=None)),
        ("form_version_question", dict(form_version_id="annex-iv-default-v1", question_id="dq2",
                                       position=1, text="Who uses it?", citation="",
                                       required=False, annex_point="1b", group_label=None)),
    ]


def other_form_rows() -> list[tuple[str, dict]]:
    return [
        ("form", dict(id="custom", name="Custom", description="", origin="builder", listed=True,
                      created_at=T0)),
        ("form", dict(id="unused", name="Unused", description="", origin="import", listed=True,
                      created_at=T0)),
        # cq1 is a copy of the default's dq1: B needs dq1 and its owner form through it.
        ("form_question", dict(id="cq1", owner_form_id="custom", scope="custom", local_id="q1",
                               copied_from_id="dq1", created_at=T0)),
        ("form_question", dict(id="cq2", owner_form_id="custom", scope="custom", local_id="q2",
                               copied_from_id=None, created_at=T0)),
        ("form_question", dict(id="uq1", owner_form_id="unused", scope="unused", local_id="q1",
                               copied_from_id=None, created_at=T0)),
        ("form_version", dict(id="custom-v1", form_id="custom", number=1, blocks=["description"],
                              created_at=T0)),
        ("form_version", dict(id="unused-v1", form_id="unused", number=1, blocks=["description"],
                              created_at=T0)),
        ("form_version_question", dict(form_version_id="custom-v1", question_id="cq1", position=0,
                                       text="Custom one", citation="", required=True,
                                       annex_point=None, group_label="g")),
        ("form_version_question", dict(form_version_id="custom-v1", question_id="cq2", position=1,
                                       text="Custom two", citation="", required=False,
                                       annex_point=None, group_label="g")),
        ("form_version_question", dict(form_version_id="unused-v1", question_id="uq1", position=0,
                                       text="Unused one", citation="", required=True,
                                       annex_point=None, group_label=None)),
    ]


def source_rows(w: World) -> list[tuple[str, dict]]:
    A, B, M, i = w.A, w.B, w.mark, w.ids
    rows: list[tuple[str, dict]] = []

    def add(t, **kv):
        rows.append((t, kv))

    add("core.project", pid=A, name="Alpha", slug=f"iso-a-{w.tag}", description=None, created_at=T0, updated_at=T0)
    add("core.project", pid=B, name="Beta", slug=f"iso-b-{w.tag}", description=None, created_at=T0, updated_at=T0)
    add("core.project_member", project_id=A, subject="alice", email=None, role="owner", added_at=T0)
    add("core.project_member", project_id=B, subject="bob", email=None, role="owner", added_at=T0)
    for key, pid, number in (("sA1", A, 1), ("sA2", A, 2), ("sB1", B, 1)):
        add("core.system", pid=i[key], project_id=pid, name="Scorer", version=str(number), provider="acme",
            description=f"card {key}", created_at=T0, updated_at=T0, number=number, created_by="alice")
    if w.forms:
        for t, r in default_form_rows() + other_form_rows():
            rows.append((f"qualification.{t}", r))
    for qid, pid, sys_key, fv in (("qA1", A, "sA1", "annex-iv-default-v1"),
                                  ("qA2", A, "sA2", "annex-iv-default-v1"),
                                  ("qB1", B, "sB1", "custom-v1")):
        r = dict(id=qid, systemName="Scorer", systemVersion="1", company="Acme", description="d",
                 targetUseCase="u", targetUsers="t", created_at=T0, updated_at=T0,
                 targetSystemTags=["a", "b"], systemCardJson=Jsonb({"k": [1, 2]}),
                 project_id=pid, system_id=i[sys_key])
        if w.forms:
            r["form_version_id"] = fv
        rows.append(("qualification.qualification", r))
    # ansA0 answers card version 1, which is not the latest: its trigger would refuse it.
    for aid, qid, q, text in (("ansA0", "qA1", "q1", "old"), ("ansA1", "qA2", "q1", f"answer {M}"),
                              ("ansA2", "qA2", "q2", "second"), ("ansB1", "qB1", "q1", "beta")):
        add("qualification.qualification_answer", id=aid, qualificationId=qid, toolId="tool", questionId=q, answer=text)
    for rid, qid in (("rA", "qA2"), ("rB", "qB1")):
        add("qualification.qualification_risk", id=rid, qualificationId=qid, position=0, risk="r", source="s",
            vulnerability=None, consequence="c", affected="a", impactAreas=["x"], control="k", followUpControl=None)
    add("qualification.knowledge_graph", id="kgA", qualificationId="qA2", digest="d", turtle="", jsonld="{}",
        stamp=["s"], nodes=1, triples=1, built_at=T0)
    add("qualification.card_component", id="ccA", qualification_id="qA2", component_pid=i["compA2"],
        airo_property="hasModel", name="m", component_type="model", object_name="", linked_at=T0)

    for coid, pid, sys_key in (("co_a", A, "sA2"), ("co_b", B, "sB1")):
        add("control_objectives.project", id=coid, name="assessment", objectives_digest="x", created_at=T0,
            updated_at=T0, project_id=pid, system_id=i[sys_key])
    add("control_objectives.graph", project_id="co_a", jsonld="{}", digest="d", risks=2, uploaded_at=T0)
    for rid, co, pos in ((1, "co_a", 0), (2, "co_a", 1), (3, "co_b", 0)):
        add("control_objectives.risk", id=rid, project_id=co, risk_id=f"R{rid}", position=pos, text="t",
            short_label="s", source="s", vulnerability="v", consequence="c", impact="i", stakeholder="st",
            control="k", follow_up_control="f", areas=["a"], vair_terms=[], provenance="p", severity=3)
    add("control_objectives.mapping_run", project_id="co_a", findings=Jsonb([{"f": 1}]), stops=Jsonb([]),
        stop="done", attempts=1, error="", model="m", ran_at=T0)
    add("control_objectives.mapped_objective", id=1, risk_row_id=1, objective_id="O1", quote="q", rationale="r")

    def ent(**kv):
        kv.setdefault("pid", str(uuid.uuid4()))
        kv.setdefault("created_at", T0)
        return kv

    for eid, pid in ((1, A), (2, B), (3, None)):
        add("engine.aisc_backend_project", **ent(id=eid, name=f"e{eid}", description="", status="active", project_id=pid))
    add("engine.aisc_backend_aisystem", **ent(id=1, name="s", description="", project_id=1))
    add("engine.aisc_backend_aisystem", **ent(id=2, name="s", description="", project_id=2))
    add("engine.aisc_backend_aicomponent", **ent(id=1, name="data", description="", data="k1", file_size=10,
                                     storage_container="c", component_type="dataset", json_value=Jsonb({}),
                                     source_dataset_id=None, system_id=1))
    add("engine.aisc_backend_aicomponent", **ent(id=2, pid=i["compA2"], name="model", description="", data="k2",
                                     file_size=None, storage_container="c", component_type="model",
                                     json_value=Jsonb({"x": 1}), source_dataset_id=1, system_id=1))
    add("engine.aisc_backend_aicomponent", **ent(id=3, name="model", description="", data="k3", file_size=None,
                                     storage_container="c", component_type="model", json_value=Jsonb({}),
                                     source_dataset_id=None, system_id=2))
    for pl, proj, cfg in ((1, 1, 1), (2, 2, None), (3, 3, None)):
        add("engine.aisc_backend_plugin", **ent(id=pl, name=f"p{pl}", description="", project_id=proj, current_config_id=cfg,
                                   package_name="pkg", version="1", display_name="P", enabled=True,
                                   catalogue_slug=None))
    add("engine.aisc_backend_pluginconfig", **ent(id=1, config=Jsonb({"k": M}), plugin_id=1, description="", name="c"))
    add("engine.aisc_backend_pluginconfig", **ent(id=2, config=Jsonb({}), plugin_id=2, description="", name="c"))
    add("engine.aisc_backend_projectconfig", **ent(id=1, name="k", description="", key="api", category="llm", updated_at=T0,
                                       encrypted_value=f"enc-{M}", masked_value="***", json_value=Jsonb({}),
                                       project_id=1))
    add("engine.aisc_backend_pluginconfigprojectconfig", **ent(id=1, name="n", description="", plugin_config_key="api",
                                                     plugin_config_id=1, project_config_id=1))
    add("engine.aisc_backend_evaluation", **ent(id=1, status="done", task=None, project_id=1, system_id=i["sA2"]))
    add("engine.aisc_backend_evaluation", **ent(id=2, status="done", task=None, project_id=2, system_id=i["sB1"]))
    add("engine.aisc_backend_evaluationplugin", **ent(id=1, name="ep", description="", evaluation_id=1, plugin_config_id=1,
                                          error_message="", finished_at=T0, started_at=T0, status="done"))
    add("engine.aisc_backend_evaluationplugin", **ent(id=2, name="ep", description="", evaluation_id=2, plugin_config_id=2,
                                          error_message="", finished_at=None, started_at=None, status="done"))
    add("engine.aisc_backend_evaluationinput", **ent(id=1, name="i", description="", value=Jsonb({"v": 1}), component_id=1,
                                         evaluation_plugin_id=1))
    add("engine.aisc_backend_artifact", **ent(id=1, name="a", description="", data="art", storage_container="c",
                                 evaluation_plugin_id=1, file_size=3))
    add("engine.aisc_backend_observation", **ent(id=1, name="o", description="", observer="o", tool="t", evaluation_id=1))
    add("engine.aisc_backend_observation", **ent(id=2, name="o", description="", observer="o", tool="t", evaluation_id=2))
    for mid, name in ((1, "acc"), (2, "f1"), (3, "f1x"), (4, "unused")):
        add("engine.aisc_backend_metric", **ent(id=mid, name=name, description="", type_spec="s"))
    add("engine.aisc_backend_direct", metric_ptr_id=1)
    add("engine.aisc_backend_derived", metric_ptr_id=3, expression="2*x", base_metric_id=2)
    for ms, obs, met, score in ((1, 1, 1, 0.1234567890123457), (2, 1, 3, 1e-300), (3, 2, 1, -0.5)):
        add("engine.aisc_backend_measurement", **ent(id=ms, name="m", description="", unit=None, time=T0, score=score,
                                        error=None, uncertainty=0.0, metric_id=met, observation_id=obs,
                                        dimensions=Jsonb({"d": ms}), direction="higher"))
    add("engine.aisc_backend_metriccategory", **ent(id=2, name="unused-cat", description=""))
    add("engine.django_content_type", id=1, app_label="aisc_backend", model="project")

    add("report_composer.template", id=i["tA"], project_id=A, name="t", font="inter", font_size_pt=10.5,
        primary_color="#000000", accent_color="#ffffff", logo_mime="image/png", logo=b"\x89PNG\x00\xff",
        created_at=T0, created_by="alice", updated_at=T0, updated_by="alice")
    for lid, pid, sys_key, tpl in (("lA", A, "sA2", i["tA"]), ("lB", B, "sB1", None)):
        add("report_composer.layout", id=i[lid], project_id=pid, system_id=i[sys_key], name="L", description="",
            revision=1, created_at=T0, created_by="alice", updated_at=T0, updated_by="alice", template_id=tpl)
    add("report_composer.layout_block", layout_id=i["lA"], instance_id=str(uuid.uuid4()), position=0,
        block_type="cover", options=Jsonb({}))
    add("report_composer.layout_block", layout_id=i["lA"], instance_id=str(uuid.uuid4()), position=1,
        block_type="summary_coverage", options=Jsonb({"links": []}))
    add("report_composer.generated_report", id=i["gA"], layout_id=i["lA"], layout_revision=1, project_id=A,
        system_id=i["sA2"], snapshot=Jsonb({"s": M}), status="done", pdf=b"%PDF-" + M.encode(),
        sha256="0" * 64, size_bytes=5, created_by="alice", created_at=T0, finished_at=T0)
    add("report_composer.preset", id=i["preset"], name="P", description="", blocks=Jsonb([]), source_project_id=A,
        created_by="alice", created_at=T0)
    return rows


#: Which primary keys each project's database must end up with.
def expected_placement(w: World) -> dict[str, dict[str, set]]:
    i = w.ids
    a = {
        "project.system": {i["sA1"], i["sA2"]},
        "qualification.qualification": {"qA1", "qA2"},
        "qualification.qualification_answer": {"ansA0", "ansA1", "ansA2"},
        "qualification.qualification_risk": {"rA"},
        "qualification.knowledge_graph": {"kgA"},
        "qualification.card_component": {"ccA"},
        "control_objectives.project": {"co_a"},
        "control_objectives.graph": {"co_a"},
        "control_objectives.risk": {1, 2},
        "control_objectives.mapping_run": {"co_a"},
        "control_objectives.mapped_objective": {1},
        "engine.aisc_backend_project": {1}, "engine.aisc_backend_aisystem": {1}, "engine.aisc_backend_aicomponent": {1, 2},
        "engine.aisc_backend_plugin": {1}, "engine.aisc_backend_pluginconfig": {1}, "engine.aisc_backend_projectconfig": {1},
        "engine.aisc_backend_pluginconfigprojectconfig": {1}, "engine.aisc_backend_evaluation": {1},
        "engine.aisc_backend_evaluationplugin": {1}, "engine.aisc_backend_evaluationinput": {1}, "engine.aisc_backend_artifact": {1},
        "engine.aisc_backend_observation": {1}, "engine.aisc_backend_metric": {1, 2, 3}, "engine.aisc_backend_direct": {1},
        "engine.aisc_backend_derived": {3}, "engine.aisc_backend_measurement": {1, 2}, "engine.aisc_backend_metriccategory": set(),
        "report_composer.template": {i["tA"]}, "report_composer.layout": {i["lA"]},
        "report_composer.generated_report": {i["gA"]},
    }
    b = {
        "project.system": {i["sB1"]},
        "qualification.qualification": {"qB1"},
        "qualification.qualification_answer": {"ansB1"},
        "qualification.qualification_risk": {"rB"},
        "qualification.knowledge_graph": set(),
        "qualification.card_component": set(),
        "control_objectives.project": {"co_b"},
        "control_objectives.graph": set(),
        "control_objectives.risk": {3},
        "control_objectives.mapping_run": set(),
        "control_objectives.mapped_objective": set(),
        "engine.aisc_backend_project": {2}, "engine.aisc_backend_aisystem": {2}, "engine.aisc_backend_aicomponent": {3},
        "engine.aisc_backend_plugin": {2}, "engine.aisc_backend_pluginconfig": {2}, "engine.aisc_backend_projectconfig": set(),
        "engine.aisc_backend_pluginconfigprojectconfig": set(), "engine.aisc_backend_evaluation": {2},
        "engine.aisc_backend_evaluationplugin": {2}, "engine.aisc_backend_evaluationinput": set(), "engine.aisc_backend_artifact": set(),
        "engine.aisc_backend_observation": {2}, "engine.aisc_backend_metric": {1}, "engine.aisc_backend_direct": {1},
        "engine.aisc_backend_derived": set(), "engine.aisc_backend_measurement": {3}, "engine.aisc_backend_metriccategory": set(),
        "report_composer.template": set(), "report_composer.layout": {i["lB"]},
        "report_composer.generated_report": set(),
    }
    if w.forms:
        # A uses the default form (equal to the seed); B uses "custom", whose cq1 copies dq1.
        a["qualification.form"] = {"annex-iv-default"}
        a["qualification.form_version"] = {"annex-iv-default-v1"}
        a["qualification.form_question"] = {"dq1", "dq2"}
        # the seed is also present in B; B's copied set adds custom and, through cq1, dq1 + its form
        b["qualification.form"] = {"annex-iv-default", "custom"}
        b["qualification.form_version"] = {"annex-iv-default-v1", "custom-v1"}
        b["qualification.form_question"] = {"dq1", "dq2", "cq1", "cq2"}
    return {w.A: a, w.B: b}


UNOWNED = {("engine.aisc_backend_project", 3), ("engine.aisc_backend_plugin", 3), ("engine.aisc_backend_metric", 4), ("engine.aisc_backend_metriccategory", 2)}


def _bookkeeping_old(conn, forms: bool) -> None:
    names = OLD_QUALIFICATION + (FORMS_MIGRATIONS if forms else [])
    for k, name in enumerate(names):
        _insert(conn, "qualification._prisma_migrations", dict(
            id=str(uuid.uuid4()), checksum="0" * 64, finished_at=T0, migration_name=name, logs=None,
            rolled_back_at=None, started_at=T0, applied_steps_count=1))
    _insert(conn, "control_objectives.alembic_version", dict(version_num=OLD_ALEMBIC))
    for k, name in enumerate(OLD_DJANGO, start=1):
        _insert(conn, "engine.django_migrations", dict(id=k, app="aisc_backend", name=name, applied=T0))
    for name in OLD_COMPOSER:
        _insert(conn, "report_composer.schema_migration", dict(name=name, applied_at=T0))
    for name in OLD_CORE:
        _insert(conn, "core.schema_migration", dict(name=name, applied_at=T0))


def _bookkeeping_new(conn, forms: bool) -> None:
    conn.execute("""CREATE TABLE IF NOT EXISTS controls._prisma_migrations (
        id varchar(36) PRIMARY KEY, checksum varchar(64) NOT NULL, finished_at timestamptz,
        migration_name varchar(255) NOT NULL, logs text, rolled_back_at timestamptz,
        started_at timestamptz NOT NULL DEFAULT now(), applied_steps_count integer NOT NULL DEFAULT 0)""")
    for table, names in (("qualification._prisma_migrations",
                          [NEW_QUALIFICATION_BASELINE] + (FORMS_MIGRATIONS if forms else [])),
                         ("controls._prisma_migrations", CONTROLS_HEAD)):
        for name in names:
            _insert(conn, table, dict(id=str(uuid.uuid4()), checksum="0" * 64, finished_at=T0,
                                      migration_name=name, logs=None, rolled_back_at=None, started_at=T0,
                                      applied_steps_count=1))
    _insert(conn, "control_objectives.alembic_version", dict(version_num=NEW_ALEMBIC))
    for k, name in enumerate(NEW_DJANGO_CHAIN, start=1):
        _insert(conn, "engine.django_migrations", dict(id=k, app="aisc_backend", name=name, applied=T0))
    _insert(conn, "report_composer.schema_migration", dict(name=NEW_COMPOSER, applied_at=T0))
    for name in NEW_TEMPLATE:
        if not (projectdb.TEMPLATE / name).is_file():
            conn.execute("INSERT INTO provision.template_migration (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))


def seed_default_form(conn, schema: str) -> None:
    for t, r in default_form_rows():
        _insert(conn, f"{schema}.{t}", r)


def build_world(forms: bool = True) -> World:
    """A fresh world; nothing of it is left behind if building it fails halfway."""
    refuse_live(SUPERUSER_DSN)
    tag = uuid.uuid4().hex[:10]
    try:
        return _build_world(forms, tag)
    except BaseException:
        a_world = World(tag=tag, source_db=f"isosrc_{tag}", A="", B="", forms=forms, mark="")
        with psycopg.connect(SUPERUSER_DSN, autocommit=True) as c:
            for (name,) in c.execute("SELECT datname FROM pg_database WHERE datname = %s", (a_world.source_db,)):
                c.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))
            for name in _PENDING_TARGETS.pop(tag, []):
                c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
        raise


_PENDING_TARGETS: dict[str, list[str]] = {}


def _build_world(forms: bool, tag: str) -> World:
    a, b = sorted(str(uuid.uuid4()) for _ in range(2))
    w = World(tag=tag, source_db=f"isosrc_{tag}", A=a, B=b, forms=forms, mark=f"ROWSECRET{uuid.uuid4().hex[:12]}")
    w.ids = {k: str(uuid.uuid4()) for k in ("sA1", "sA2", "sB1", "compA2", "tA", "lA", "lB", "gA", "preset")}
    with psycopg.connect(SUPERUSER_DSN, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(w.source_db)))
    with w.source() as c:
        with c.transaction():  # one commit, not one per statement
            c.execute("CREATE SCHEMA core")  # made by init/platform-db.sql live; the dump starts inside it
            for s in source_statements(forms):
                c.execute(s)
            c.execute("SET search_path = public")
            for s in library_statements():
                if not forms and "form_library." in s:
                    continue
                c.execute(s)
        with c.transaction():
            c.execute("SET LOCAL session_replication_role = replica")
            for t, r in source_rows(w):
                _insert(c, t, r)
            if forms:
                seed_default_form(c, "form_library")
            _bookkeeping_old(c, forms)
        c.execute("SELECT setval('control_objectives.risk_id_seq', 10, true)")
        c.execute("SELECT setval('control_objectives.mapped_objective_id_seq', 1, true)")
        c.execute("SELECT setval('engine.aisc_backend_project_id_seq', 72, true)")
        # below max(id) on purpose: the target takes max(source last_value, max(target id))
        c.execute("SELECT setval('engine.aisc_backend_metric_id_seq', 1, true)")
        c.execute("SELECT setval('engine.aisc_backend_plugin_id_seq', 30, false)")
    _PENDING_TARGETS[tag] = [w.target_db(p) for p in w.pids]
    for pid in w.pids:
        make_target(w, pid)
    _PENDING_TARGETS.pop(tag, None)
    return w


def make_target(w: World, pid: str) -> None:
    projectdb.provision(PLATFORM_RW_DSN, pid)
    with w.target(pid) as c, c.transaction():
        c.execute(PROJECT_SYSTEM_DDL)
        for s in target_statements(w.forms):
            c.execute(s)
        c.execute("SET search_path = public")
        if w.forms:
            seed_default_form(c, "qualification")
        _bookkeeping_new(c, w.forms)


def drop_world(w: World) -> None:
    with psycopg.connect(SUPERUSER_DSN, autocommit=True) as c:
        for name in [w.target_db(p) for p in w.pids] + [w.source_db] + list(w.ids.get("_extra_dbs", [])):
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


@contextmanager
def world(forms: bool = True):
    w = build_world(forms)
    try:
        yield w
    finally:
        drop_world(w)


# Observing databases.


def user_tables(conn) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT n.nspname || '.' || c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
        " WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
        "   AND n.nspname NOT LIKE 'pg_toast%' ORDER BY 1").fetchall()]


def columns(conn, table: str) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT attname FROM pg_attribute WHERE attrelid = %s::regclass AND attnum > 0 AND NOT attisdropped"
        " ORDER BY attnum", (table,)).fetchall()]


def checksum(conn, table: str, cols: list[str], where: sql.Composable | None = None) -> tuple[int, str]:
    """Count and md5(string_agg(row_text, E'\\n' ORDER BY row_text)), row_text = ROW(cols)::text."""
    conn.execute(ROW_TEXT_SETTINGS)
    q = sql.SQL(
        "SELECT count(*), md5(coalesce(string_agg(r, E'\\n' ORDER BY r), '')) FROM"
        " (SELECT ROW({cols})::text AS r FROM {t} {w}) s"
    ).format(cols=sql.SQL(", ").join(sql.Identifier(c) for c in cols),
             t=sql.Identifier(*table.split(".")),
             w=sql.SQL("WHERE ") + where if where is not None else sql.SQL(""))
    n, md5 = conn.execute(q).fetchone()
    return n, md5


def digests(dsn: str, schemas: tuple[str, ...] | None = None) -> dict[str, tuple[int, str]]:
    """Every user table of a database, count + checksum over all its columns."""
    with psycopg.connect(dsn, autocommit=True) as c:
        out = {}
        for t in user_tables(c):
            if schemas and t.split(".")[0] not in schemas:
                continue
            out[t] = checksum(c, t, columns(c, t))
        return out


def keys(conn, table: str, pk: str) -> set:
    return {r[0] for r in conn.execute(
        sql.SQL("SELECT {} FROM {}").format(sql.Identifier(pk), sql.Identifier(*table.split(".")))).fetchall()}


def primary_key(conn, table: str) -> str:
    rows = conn.execute(
        "SELECT a.attname FROM pg_index i JOIN pg_attribute a ON a.attrelid = i.indrelid"
        " AND a.attnum = ANY(i.indkey) WHERE i.indrelid = %s::regclass AND i.indisprimary", (table,)).fetchall()
    return rows[0][0]


def fk_orphans(conn) -> list[str]:
    """Every foreign key of the database checked by an anti-join (the database's own check can be
    bypassed by session_replication_role, which is how the fixture inserts)."""
    out = []
    fks = conn.execute(
        "SELECT conrelid::regclass::text, confrelid::regclass::text, conname,"
        " (SELECT array_agg(attname ORDER BY k.ord) FROM unnest(conkey) WITH ORDINALITY k(n, ord)"
        "   JOIN pg_attribute ON attrelid = conrelid AND attnum = k.n),"
        " (SELECT array_agg(attname ORDER BY k.ord) FROM unnest(confkey) WITH ORDINALITY k(n, ord)"
        "   JOIN pg_attribute ON attrelid = confrelid AND attnum = k.n)"
        " FROM pg_constraint WHERE contype = 'f'").fetchall()
    for child, parent, name, ccols, pcols in fks:
        cond = sql.SQL(" AND ").join(
            sql.SQL("p.{} = c.{}").format(sql.Identifier(pc), sql.Identifier(cc)) for cc, pc in zip(ccols, pcols))
        notnull = sql.SQL(" AND ").join(sql.SQL("c.{} IS NOT NULL").format(sql.Identifier(cc)) for cc in ccols)
        q = sql.SQL("SELECT count(*) FROM {} c WHERE {} AND NOT EXISTS (SELECT 1 FROM {} p WHERE {})").format(
            sql.SQL(child), notnull, sql.SQL(parent), cond)
        if conn.execute(q).fetchone()[0]:
            out.append(f"{child}.{name}")
    return out


def written_tuples(dbnames: list[str]) -> dict[str, tuple[int, int, int]]:
    """Rows inserted, updated and deleted per database (pg_stat_database), read from the cluster's
    `postgres` database. xact_commit moves on every new connection, which the tool needs to read
    its targets, so it cannot tell reading from writing; these counters only move when a row is
    written. Waits for the stats to settle."""
    time.sleep(2.0)
    with psycopg.connect(dsn_for("postgres"), autocommit=True) as c:
        c.execute("SELECT pg_stat_clear_snapshot()")
        return {d: (i, u, x) for d, i, u, x in c.execute(
            "SELECT datname, tup_inserted, tup_updated, tup_deleted FROM pg_stat_database"
            " WHERE datname = ANY(%s)", (dbnames,)).fetchall()}


def tuple_counters(dsn: str, schemas: tuple[str, ...]) -> dict[str, tuple[int, int, int]]:
    time.sleep(2.0)
    with psycopg.connect(dsn, autocommit=True) as c:
        c.execute("SELECT pg_stat_clear_snapshot()")
        return {f"{s}.{t}": (i, u, d) for s, t, i, u, d in c.execute(
            "SELECT schemaname, relname, n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables"
            " WHERE schemaname = ANY(%s)", (list(schemas),)).fetchall()}


def quiet_cluster() -> None:
    """Autovacuum off on the throwaway cluster, so that xact_commit only moves when something
    connects on purpose (an autovacuum worker commits transactions in every database it visits)."""
    refuse_live(SUPERUSER_DSN)
    with psycopg.connect(SUPERUSER_DSN, autocommit=True) as c:
        c.execute("ALTER SYSTEM SET autovacuum = off")
        c.execute("SELECT pg_reload_conf()")


# Running the tool.


class Result:
    def __init__(self, returncode: int, stdout: str, stderr: str, report: dict | None):
        self.returncode, self.stdout, self.stderr, self.report = returncode, stdout, stderr, report

    @property
    def output(self) -> str:
        return self.stdout + "\n" + self.stderr

    def refusals(self) -> list[dict]:
        return list((self.report or {}).get("refusals") or [])

    def status(self, pid: str) -> str | None:
        return ((self.report or {}).get("projects") or {}).get(pid, {}).get("status")


#: Fixture self-check: ISOLATE_TESTS_PROBE=1 makes the tests run their setup and mutations
#: without the tool (every run "fails" with code 99), so a broken fixture shows on its own.
PROBE = os.environ.get("ISOLATE_TESTS_PROBE") == "1"


def require_tool():
    """Import the tool under test (platform_service.isolate), inside each test, so a broken
    import fails those tests only and the rest of the platform suite still collects."""
    if PROBE:
        return None
    import importlib

    return importlib.import_module("platform_service.isolate")


def run(w: World, *args: str, report: Path | None = None, env: dict | None = None,
        timeout: int = 300) -> Result:
    """python -m platform_service.isolate <args> [--report <path>], as the superuser of the
    throwaway cluster, the world's source database standing for `platform`.

    Every run is checked for leaks: no row value (MARK) and no password in stdout, stderr or the
    report file, whatever the test is about."""
    argv = [shutil.which("python") or "python", "-m", "platform_service.isolate", *args]
    if report is not None:
        argv += ["--report", str(report)]
    e = dict(os.environ)
    e["ISOLATE_SUPERUSER_URL"] = w.source_dsn
    e.update(env or {})
    if PROBE:
        return Result(99, "", "probe", None)
    p = subprocess.run(argv, cwd=PLATFORM_DIR, env=e, capture_output=True, text=True, timeout=timeout)
    text = report.read_text() if report is not None and report.exists() else ""
    import json

    data = json.loads(text) if text.strip() else None
    pw = password_of(SUPERUSER_DSN)
    for where, body in (("stdout", p.stdout), ("stderr", p.stderr), ("report", text)):
        assert w.mark not in body, f"I12.16/I12.15: a row value leaked into the tool's {where}"
        assert not pw or pw not in body, f"I12.16/I18.7: the superuser password leaked into the tool's {where}"
    return Result(p.returncode, p.stdout, p.stderr, data)


def assert_refused(res: Result, reasons: str | set[str], *, table: str | None = None,
                   projects: tuple[str, ...] = ()) -> dict:
    """Assert a refusal: non-zero exit, a named reason in the report and in the output."""
    reasons = {reasons} if isinstance(reasons, str) else reasons
    assert res.returncode != 0, f"expected a refusal ({sorted(reasons)}), exit was 0:\n{res.output[-2000:]}"
    hits = [r for r in res.refusals() if r.get("reason") in reasons
            and (table is None or r.get("table") == table)]
    assert hits, f"no refusal {sorted(reasons)} on {table} in report: {res.refusals()}"
    assert any(reason in res.output for reason in reasons), f"reason {sorted(reasons)} not printed"
    for pid in projects:
        assert any(pid in (h.get("projects") or [h.get("project")]) for h in hits), \
            f"refusal does not name project {pid}: {hits}"
    return hits[0]
