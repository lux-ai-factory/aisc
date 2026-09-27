"""The report's database roles and grants (report run 2026-09-23: 01-specs R4.1.3, R6.1, R6.5,
R7.3.3, R7.3.6; 02 D6 (a)(b)(c), D13).

Every database here is the report test bed (scripts/lib/report_bed.py): a throwaway
postgres:14-alpine container on a free port, never the host's 5432, removed at session end. The
bed applies init/report-roles.sql, scripts/report-grants.sh (with init/report-ro-grants.sql) and
platform/project-template/0003_report.sql when they exist; until stage 5 writes them, these tests
fail on the missing role or privilege, which is the feature they test.

    uv run --no-project --with pytest python -m pytest -q -p no:cacheprovider scripts/tests/test_report_grants.py
"""

import sys
import uuid

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts/lib"))
import report_bed  # noqa: E402

IDS = report_bed.IDS
ROLES_SQL = ROOT / "init/report-roles.sql"
GRANTS_SQL = ROOT / "init/report-ro-grants.sql"

QUALIFICATION = ["qualification", "card_component", "knowledge_graph", "qualification_risk"]
CONTROL_OBJECTIVES = ["project", "risk", "mapped_objective", "mapping_run"]
ENGINE = ["project", "evaluation", "evaluation_plugin", "evaluation_input", "plugin", "ai_component",
          "observation", "measurement", "metric", "artifact"]
SUPERSET = ["aisc_comment", "dashboards", "dashboard_roles", "ab_role", "dashboard_slices", "slices",
            "tables"]
CONTROLS = ["checklist", "checklist_question", "submission", "submission_answer", "source"]
ENGINE_FORBIDDEN = ["auth_user", "django_session", "project_config", "account_emailaddress",
                    "plugin_config_project_config"]


@pytest.fixture(scope="session")
def bed():
    report_bed.check_dsn_env()
    b = report_bed.build("grants")
    yield b
    b.stop()


def ok(r):
    return r.returncode == 0


def as_ro(bed, db, sql):
    return bed.psql(db, sql, role="report_ro", check=False)


def need(path):
    assert path.exists(), f"missing feature: {path.relative_to(ROOT)}"


# ── report_ro: the role ──────────────────────────────────────────────────────


def test_d6a_report_roles_sql_reruns_idempotently(bed):
    """D6 (a), D13, R4.1.3: init/report-roles.sql runs as the superuser on every postgres-setup
    start, so a second run changes nothing and does not fail."""
    need(ROLES_SQL)
    r = bed.psql("platform", ROLES_SQL.read_text(), check=False)
    assert ok(r), r.stderr[-2000:]


def test_d6a_report_ro_logs_in_read_only(bed):
    """R6.1, D6 (a): report_ro is LOGIN and its sessions default to read-only transactions."""
    rows = bed.rows("platform", "SELECT rolcanlogin, rolconfig FROM pg_roles WHERE rolname = 'report_ro'")
    assert rows, "missing feature: role report_ro"
    assert rows[0]["rolcanlogin"]
    assert "default_transaction_read_only=on" in (rows[0]["rolconfig"] or [])
    r = as_ro(bed, "platform", "SHOW default_transaction_read_only")
    assert ok(r), r.stderr


def test_r6_1_report_ro_reads_core(bed):
    """R6.1, D6 (a): SELECT on core.project and core.system."""
    for t in ("core.project", "core.system"):
        r = as_ro(bed, "platform", f"SELECT count(*) FROM {t}")
        assert ok(r), f"{t}: {r.stderr}"


@pytest.mark.parametrize("schema,table", [("qualification", t) for t in QUALIFICATION]
                         + [("control_objectives", t) for t in CONTROL_OBJECTIVES]
                         + [("engine", t) for t in ENGINE])
def test_r6_1_report_ro_reads_the_listed_tables(bed, schema, table):
    """R6.1, D6 (b): SELECT on exactly the tables the blocks read."""
    r = as_ro(bed, "platform", f"SELECT count(*) FROM {schema}.{table}")
    assert ok(r), r.stderr


def test_d6b_plugin_config_is_readable_by_column_only(bed):
    """D6 (b): plugin_config.config may hold tool settings; report_ro gets (id, plugin_id) only."""
    r = as_ro(bed, "platform", "SELECT id, plugin_id FROM engine.plugin_config")
    assert ok(r), r.stderr
    r = as_ro(bed, "platform", "SELECT config FROM engine.plugin_config")
    assert not ok(r) and "permission denied" in r.stderr


@pytest.mark.parametrize("table", ENGINE_FORBIDDEN)
def test_d6b_engine_tables_outside_the_list_are_refused(bed, table):
    """D6 (b): never auth_*, django_*, project_config, plugin_config_project_config, account_*.
    The role must exist and connect first, so this cannot pass by the role being absent."""
    assert ok(as_ro(bed, "platform", "SELECT 1")), "missing feature: report_ro cannot connect"
    r = as_ro(bed, "platform", f"SELECT 1 FROM engine.{table} LIMIT 1")
    assert not ok(r)


def test_r6_5_report_ro_never_reads_the_catalogue(bed):
    """R6.5: no privilege on the catalogue schema."""
    rows = bed.rows("platform", "SELECT has_schema_privilege('report_ro', 'catalogue', 'USAGE') AS u"
                    " FROM pg_roles WHERE rolname = 'report_ro'")
    assert rows, "missing feature: role report_ro"
    assert rows[0]["u"] is False
    assert not ok(as_ro(bed, "platform", "SELECT 1 FROM catalogue.tool LIMIT 1"))


@pytest.mark.parametrize("table", SUPERSET)
def test_d6b_report_ro_reads_the_superset_tables(bed, table):
    """R6.1, D5, D6 (b): in superset, SELECT on the seven tables of chart ownership and comments."""
    r = as_ro(bed, "superset", f"SELECT count(*) FROM public.{table}")
    assert ok(r), r.stderr


def test_d6b_report_ro_does_not_read_superset_users(bed):
    """D6 (b): nothing else in superset, e.g. ab_user (password hashes)."""
    assert ok(as_ro(bed, "superset", "SELECT 1")), "missing feature: report_ro cannot connect to superset"
    r = as_ro(bed, "superset", "SELECT 1 FROM public.ab_user LIMIT 1")
    assert not ok(r) and "permission denied" in r.stderr


@pytest.mark.parametrize("key", ["A", "B", "E"])
def test_d6c_report_ro_reads_controls_of_each_project(bed, key):
    """R6.1, D6 (c): in every project database, CONNECT, USAGE on controls and SELECT on its five
    tables."""
    db = report_bed.project_db(IDS[key])
    for t in CONTROLS:
        r = as_ro(bed, db, f"SELECT count(*) FROM controls.{t}")
        assert ok(r), f"{db} controls.{t}: {r.stderr}"


# ── read-only means read-only ────────────────────────────────────────────────


@pytest.mark.parametrize("db,sql", [
    ("platform", "INSERT INTO core.project (name, slug) VALUES ('x', 'report-ro-x')"),
    ("platform", "UPDATE qualification.qualification SET description = 'x'"),
    ("platform", "DELETE FROM engine.measurement"),
    ("platform", "CREATE TABLE core.report_ro_probe (x int)"),
    ("superset", "UPDATE aisc_comment SET body = 'x'"),
])
def test_r6_1_every_write_is_refused(bed, db, sql):
    """R6.1, R7.3.6: when any write is attempted as report_ro, the database refuses it."""
    assert ok(as_ro(bed, db, "SELECT 1")), "missing feature: report_ro cannot connect"
    r = as_ro(bed, db, sql)
    assert not ok(r)
    assert "read-only transaction" in r.stderr or "permission denied" in r.stderr, r.stderr


def test_r6_1_a_write_in_a_project_database_is_refused(bed):
    """R6.1: the same in a project database."""
    db = report_bed.project_db(IDS["A"])
    assert ok(as_ro(bed, db, "SELECT 1")), "missing feature: report_ro cannot connect"
    r = as_ro(bed, db, "DELETE FROM controls.submission_answer")
    assert not ok(r)


def test_r6_1_read_only_even_when_the_session_asks_otherwise(bed):
    """R6.1: turning read-only off in the session does not give write privileges."""
    assert ok(as_ro(bed, "platform", "SELECT 1")), "missing feature: report_ro cannot connect"
    r = as_ro(bed, "platform", "SET default_transaction_read_only = off;\n"
              "INSERT INTO core.project (name, slug) VALUES ('x', 'report-ro-y')")
    assert not ok(r) and "permission denied" in r.stderr


# ── no accidental reach ──────────────────────────────────────────────────────


def test_d6b_a_new_module_table_is_not_readable(bed):
    """D6 (b): no ALTER DEFAULT PRIVILEGES on module schemas, so a table engine_rw creates later
    is not readable by report_ro (while the listed ones are)."""
    assert ok(as_ro(bed, "platform", "SELECT 1 FROM engine.evaluation LIMIT 1")), \
        "missing feature: report_ro cannot read engine.evaluation"
    name = f"probe_{uuid.uuid4().hex[:8]}"
    r = bed.psql("platform", f"CREATE TABLE engine.{name} (x int)", role="engine_rw", check=False)
    assert ok(r), r.stderr
    r = as_ro(bed, "platform", f"SELECT 1 FROM engine.{name}")
    assert not ok(r) and "permission denied" in r.stderr


def test_d6c_a_project_database_made_later_is_readable(bed):
    """D6 (c): a project database created after the grants (by platform_rw, from template1 and the
    project template incl. 0003_report.sql, controls schema made by controls_rw) is readable by
    report_ro through template1's default privileges FOR ROLE controls_rw."""
    pid = str(uuid.uuid4())
    db = report_bed._project_database(bed.t, pid)
    for t in CONTROLS:
        r = as_ro(bed, db, f"SELECT count(*) FROM controls.{t}")
        assert ok(r), f"{db} controls.{t}: {r.stderr}"


def test_d6b_grants_sql_skips_tables_that_do_not_exist_yet():
    """D6 (b): init/report-ro-grants.sql is idempotent and skips a table whose to_regclass is null,
    so it succeeds on a database with no module schemas at all."""
    need(ROLES_SQL)
    need(GRANTS_SQL)
    b = report_bed.build("grants-empty", modules=False, seed=False)
    try:
        for _ in range(2):
            r = b.psql("platform", GRANTS_SQL.read_text(), check=False)
            assert ok(r), r.stderr[-2000:]
    finally:
        b.stop()


# ── report_composer_rw ───────────────────────────────────────────────────────


def test_d13_composer_role_owns_its_schema(bed):
    """R4.1.3, D13: schema report_composer exists and is owned by report_composer_rw."""
    rows = bed.rows("platform", "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace"
                    " WHERE nspname = 'report_composer'")
    assert rows, "missing feature: schema report_composer"
    assert rows[0]["owner"] == "report_composer_rw"


def test_d13_composer_role_search_path(bed):
    """D13: report_composer_rw's search_path in platform is report_composer, core."""
    r = bed.psql("platform", "SHOW search_path", role="report_composer_rw", check=False)
    assert ok(r), f"missing feature: report_composer_rw cannot connect: {r.stderr}"
    rows = bed.rows("platform", "SELECT unnest(s.setconfig) AS c FROM pg_db_role_setting s"
                    " JOIN pg_roles r ON r.oid = s.setrole JOIN pg_database d ON d.oid = s.setdatabase"
                    " WHERE r.rolname = 'report_composer_rw' AND d.datname = 'platform'")
    assert any(x["c"].replace(" ", "") == "search_path=report_composer,core" for x in rows), rows


def test_d13_composer_role_can_reference_core(bed):
    """R3.1, D13: the composer may create its tables with foreign keys to core.project and
    core.system (REFERENCES), in its own schema."""
    name = f"probe_{uuid.uuid4().hex[:8]}"
    r = bed.psql("platform",
                 f"CREATE TABLE report_composer.{name} (p uuid REFERENCES core.project(pid),"
                 f" s uuid REFERENCES core.system(pid)); DROP TABLE report_composer.{name};",
                 role="report_composer_rw", check=False)
    assert ok(r), r.stderr


def test_r4_4_2_composer_role_reads_memberships(bed):
    """R4.4.2, D13: SELECT on core.project, core.system and core.project_member."""
    for t in ("core.project", "core.system", "core.project_member"):
        r = bed.psql("platform", f"SELECT count(*) FROM {t}", role="report_composer_rw", check=False)
        assert ok(r), f"{t}: {r.stderr}"


def test_d13_composer_role_never_writes_core(bed):
    """R4.1.3: nothing but its own schema: no write on core."""
    assert ok(bed.psql("platform", "SELECT 1", role="report_composer_rw", check=False)), \
        "missing feature: report_composer_rw cannot connect"
    r = bed.psql("platform", "INSERT INTO core.project (name, slug) VALUES ('x', 'composer-x')",
                 role="report_composer_rw", check=False)
    assert not ok(r) and "permission denied" in r.stderr


@pytest.mark.parametrize("table", ["qualification.qualification", "engine.evaluation",
                                   "control_objectives.project"])
def test_r7_3_3_composer_never_reads_module_schemas(bed, table):
    """R7.3.3: the composer never reads module schemas; only the renderer does, as report_ro."""
    assert ok(bed.psql("platform", "SELECT 1", role="report_composer_rw", check=False)), \
        "missing feature: report_composer_rw cannot connect"
    r = bed.psql("platform", f"SELECT 1 FROM {table} LIMIT 1", role="report_composer_rw", check=False)
    assert not ok(r) and "permission denied" in r.stderr


def test_r7_3_3_composer_cannot_reach_projects_or_comments(bed):
    """R7.3.3: no CONNECT on the project databases, no read of superset's comments."""
    assert ok(bed.psql("platform", "SELECT 1", role="report_composer_rw", check=False)), \
        "missing feature: report_composer_rw cannot connect"
    r = bed.psql(report_bed.project_db(IDS["A"]), "SELECT 1", role="report_composer_rw", check=False)
    assert not ok(r)
    r = bed.psql("superset", "SELECT 1 FROM public.aisc_comment LIMIT 1", role="report_composer_rw",
                 check=False)
    assert not ok(r)
