"""The report's database roles and grants (report run 2026-09-23: 01-specs R4.1.3, R6.1, R6.5,
R7.3.3, R7.3.6; 02 D6 (a)(b)(c), D13), in the isolated layout (isolation 2026-09-25: I1.4, I2.1, I2.6,
I2.7, I8.1).

Rewritten by WP V1 (S-D13: the approved design moves every module table into the project's own
database). The bed is scripts/lib/report_bed_isolated.py: a throwaway postgres:15-alpine container on a
free port, never the host's 5432, removed at session end, in the state the move tool and the stage-7 drop
leave behind. What moved, and how the cases follow it:

- report_ro reads the module tables of the report inside each project database (A, B, E), not in
  `platform`; in `platform` it reads core.project only (I1.4), core.system is gone.
- a project database made later is readable after the next scripts/report-grants.sh run (I2.7), never
  through a default privilege in template1 (I2.6 forbids them).
- the composer (R1's final grants): in `platform` it owns report_library and reads core.project and
  core.project_member; in each project database it may connect and has USAGE, CREATE on report_composer,
  USAGE on project and SELECT, REFERENCES on project.system, and nothing of the other modules.

    uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_report_grants.py
"""

import sys
import uuid

import pytest

from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts/lib"))
import report_bed  # noqa: E402
import report_bed_isolated  # noqa: E402

IDS = report_bed.IDS
ROLES_SQL = ROOT / "init/report-roles.sql"
GRANTS_SQL = ROOT / "init/report-ro-grants.sql"
PROJECTS = ["A", "B", "E"]

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
    b = report_bed_isolated.build_isolated("grants")
    yield b
    b.stop()


def ok(r):
    return r.returncode == 0


def as_ro(bed, db, sql):
    return bed.psql(db, sql, role="report_ro", check=False)


def as_composer(bed, db, sql):
    return bed.psql(db, sql, role="report_composer_rw", check=False)


def need(path):
    assert path.exists(), f"missing feature: {path.relative_to(ROOT)}"


def db_of(key):
    return report_bed.project_db(IDS[key])


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
    """R6.1, I1.4: in platform, SELECT on core.project and nothing else of core; core.system is gone."""
    r = as_ro(bed, "platform", "SELECT count(*) FROM core.project")
    assert ok(r), r.stderr
    assert bed.scalar("platform", "SELECT to_regclass('core.system') IS NULL") == "t"
    assert bed.scalar("platform", "SELECT has_table_privilege('report_ro', 'core.project_member', 'SELECT')") == "f"


@pytest.mark.parametrize("key", PROJECTS)
def test_r6_1_report_ro_reads_the_card_versions_of_each_project(bed, key):
    """R6.1, I2.6: project.system in every project database."""
    r = as_ro(bed, db_of(key), "SELECT count(*) FROM project.system")
    assert ok(r), r.stderr


@pytest.mark.parametrize("schema,table", [("qualification", t) for t in QUALIFICATION]
                         + [("control_objectives", t) for t in CONTROL_OBJECTIVES]
                         + [("engine", t) for t in ENGINE])
def test_r6_1_report_ro_reads_the_listed_tables(bed, schema, table):
    """R6.1, D6 (b), I2.6: SELECT on the tables the blocks read, in every project database."""
    for key in PROJECTS:
        r = as_ro(bed, db_of(key), f"SELECT count(*) FROM {schema}.{table}")
        assert ok(r), f"{db_of(key)}: {r.stderr}"


def test_d6b_plugin_config_is_readable_by_column_only(bed):
    """D6 (b), I2.6: plugin_config.config may hold tool settings; report_ro gets (id, plugin_id) only."""
    db = db_of("A")
    r = as_ro(bed, db, "SELECT id, plugin_id FROM engine.plugin_config")
    assert ok(r), r.stderr
    r = as_ro(bed, db, "SELECT config FROM engine.plugin_config")
    assert not ok(r) and "permission denied" in r.stderr


@pytest.mark.parametrize("table", ENGINE_FORBIDDEN)
def test_d6b_engine_tables_outside_the_list_are_refused(bed, table):
    """D6 (b): never auth_*, django_*, project_config, plugin_config_project_config, account_*.
    The role must exist and connect first, so this cannot pass by the role being absent."""
    db = db_of("A")
    assert ok(as_ro(bed, db, "SELECT 1")), "missing feature: report_ro cannot connect"
    r = as_ro(bed, db, f"SELECT 1 FROM engine.{table} LIMIT 1")
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


@pytest.mark.parametrize("key", PROJECTS)
def test_d6c_report_ro_reads_controls_of_each_project(bed, key):
    """R6.1, D6 (c): in every project database, CONNECT, USAGE on controls and SELECT on its five
    tables."""
    db = db_of(key)
    for t in CONTROLS:
        r = as_ro(bed, db, f"SELECT count(*) FROM controls.{t}")
        assert ok(r), f"{db} controls.{t}: {r.stderr}"


# ── read-only means read-only ────────────────────────────────────────────────


@pytest.mark.parametrize("where,sql", [
    ("platform", "INSERT INTO core.project (name, slug) VALUES ('x', 'report-ro-x')"),
    ("A", "UPDATE qualification.qualification SET description = 'x'"),
    ("A", "DELETE FROM engine.measurement"),
    ("platform", "CREATE TABLE core.report_ro_probe (x int)"),
    ("A", "CREATE TABLE engine.report_ro_probe (x int)"),
    ("superset", "UPDATE aisc_comment SET body = 'x'"),
])
def test_r6_1_every_write_is_refused(bed, where, sql):
    """R6.1, R7.3.6: when any write is attempted as report_ro, the database refuses it."""
    db = db_of(where) if where in IDS else where
    assert ok(as_ro(bed, db, "SELECT 1")), "missing feature: report_ro cannot connect"
    r = as_ro(bed, db, sql)
    assert not ok(r)
    assert "read-only transaction" in r.stderr or "permission denied" in r.stderr, r.stderr


def test_r6_1_a_write_in_a_project_database_is_refused(bed):
    """R6.1: the same for the controls answers of a project database."""
    db = db_of("A")
    assert ok(as_ro(bed, db, "SELECT 1")), "missing feature: report_ro cannot connect"
    r = as_ro(bed, db, "DELETE FROM controls.submission_answer")
    assert not ok(r)


def test_r6_1_read_only_even_when_the_session_asks_otherwise(bed):
    """R6.1: turning read-only off in the session does not give write privileges."""
    for db, sql in (("platform", "INSERT INTO core.project (name, slug) VALUES ('x', 'report-ro-y')"),
                    (db_of("A"), "DELETE FROM engine.measurement")):
        assert ok(as_ro(bed, db, "SELECT 1")), "missing feature: report_ro cannot connect"
        r = as_ro(bed, db, "SET default_transaction_read_only = off;\n" + sql)
        assert not ok(r) and "permission denied" in r.stderr, (db, r.stderr)


# ── no accidental reach ──────────────────────────────────────────────────────


def test_d6b_a_new_module_table_is_not_readable(bed):
    """D6 (b), I2.6: no default privileges, so a table engine_rw creates later in a project database is not
    readable by report_ro (while the listed ones are), not even after report-grants.sh repairs the list."""
    db = db_of("A")
    assert ok(as_ro(bed, db, "SELECT 1 FROM engine.evaluation LIMIT 1")), \
        "missing feature: report_ro cannot read engine.evaluation"
    name = f"probe_{uuid.uuid4().hex[:8]}"
    r = bed.psql(db, f"CREATE TABLE engine.{name} (x int)", role="engine_rw", check=False)
    assert ok(r), r.stderr
    r = as_ro(bed, db, f"SELECT 1 FROM engine.{name}")
    assert not ok(r) and "permission denied" in r.stderr
    g = report_bed.run_report_grants(bed.t)
    assert ok(g), (g.stdout + g.stderr)[-1500:]
    r = as_ro(bed, db, f"SELECT 1 FROM engine.{name}")
    assert not ok(r) and "permission denied" in r.stderr


def test_d6c_a_project_database_made_later_is_readable_after_the_next_grants_run(bed):
    """D6 (c), I2.6, I2.7: a project database created after the grants (by platform_rw, from template1 and
    the project template, schema controls made by controls_rw) whose module did not grant the readers
    (here: its grants taken back, as for a database migrated before report_ro existed) is not readable
    through any default privilege; the next scripts/report-grants.sh run makes its listed tables readable."""
    pid = str(uuid.uuid4())
    db = report_bed._project_database(bed.t, pid)
    bed.psql(db, "REVOKE SELECT ON ALL TABLES IN SCHEMA controls FROM report_ro, dashboard_ro")
    r = as_ro(bed, db, "SELECT count(*) FROM controls.submission_answer")
    assert not ok(r) and "permission denied" in r.stderr, "I2.6: readable before the repair: a default privilege"
    g = report_bed.run_report_grants(bed.t)
    assert ok(g), (g.stdout + g.stderr)[-1500:]
    assert bed.t.password not in g.stdout + g.stderr
    for t in CONTROLS:
        r = as_ro(bed, db, f"SELECT count(*) FROM controls.{t}")
        assert ok(r), f"{db} controls.{t}: {r.stderr}"
    assert not ok(as_ro(bed, db, 'SELECT 1 FROM controls."_prisma_migrations" LIMIT 1'))


def test_d6b_grants_sql_skips_tables_that_do_not_exist_yet():
    """D6 (b): init/report-ro-grants.sql is idempotent and skips a table whose to_regclass is null,
    so it succeeds on a cluster with no module schemas and no superset tables at all."""
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


def test_d13_composer_role_owns_its_library_and_its_project_schema(bed):
    """R4.1.3, D13, I8.1: in platform the composer owns report_library; in a project database its schema
    report_composer is the template's (owner platform_rw) with USAGE, CREATE for the composer."""
    rows = bed.rows("platform", "SELECT pg_get_userbyid(nspowner) AS owner FROM pg_namespace"
                    " WHERE nspname = 'report_library'")
    assert rows, "missing feature: schema report_library"
    assert rows[0]["owner"] == "report_composer_rw"
    assert bed.scalar("platform", "SELECT to_regnamespace('report_composer') IS NULL") == "t"
    for key in PROJECTS:
        db = db_of(key)
        for priv in ("USAGE", "CREATE"):
            assert bed.scalar(db, f"SELECT has_schema_privilege('report_composer_rw', 'report_composer', '{priv}')") == "t"


def test_d13_composer_role_search_path(bed):
    """D13, I2.1: report_composer_rw's search_path is report_library, core in platform, and
    report_composer alone in a project database."""
    r = bed.psql("platform", "SHOW search_path", role="report_composer_rw", check=False)
    assert ok(r), f"missing feature: report_composer_rw cannot connect: {r.stderr}"

    def settings(db):
        return [x["c"].replace(" ", "") for x in bed.rows(db, "SELECT unnest(s.setconfig) AS c FROM pg_db_role_setting s"
                " JOIN pg_roles r ON r.oid = s.setrole JOIN pg_database d ON d.oid = s.setdatabase"
                f" WHERE r.rolname = 'report_composer_rw' AND d.datname = '{db}'")]
    assert "search_path=report_library,core" in settings("platform"), settings("platform")
    assert "search_path=report_composer" in settings(db_of("A")), settings(db_of("A"))


def test_d13_composer_role_can_reference_its_card_versions(bed):
    """R3.1, D13, I1.6: the composer may create its tables with a foreign key to project.system
    (REFERENCES), in its own schema of a project database."""
    name = f"probe_{uuid.uuid4().hex[:8]}"
    r = as_composer(bed, db_of("A"),
                    f"CREATE TABLE report_composer.{name} (s uuid REFERENCES project.system(pid));"
                    f" DROP TABLE report_composer.{name};")
    assert ok(r), r.stderr


def test_r4_4_2_composer_role_reads_memberships(bed):
    """R4.4.2, D13: SELECT on core.project and core.project_member in platform, and on project.system in a
    project database."""
    for t in ("core.project", "core.project_member"):
        r = as_composer(bed, "platform", f"SELECT count(*) FROM {t}")
        assert ok(r), f"{t}: {r.stderr}"
    r = as_composer(bed, db_of("A"), "SELECT count(*) FROM project.system")
    assert ok(r), r.stderr


def test_d13_composer_role_never_writes_core(bed):
    """R4.1.3: nothing but its own schemas: no write on core, none on project.system."""
    assert ok(as_composer(bed, "platform", "SELECT 1")), "missing feature: report_composer_rw cannot connect"
    r = as_composer(bed, "platform", "INSERT INTO core.project (name, slug) VALUES ('x', 'composer-x')")
    assert not ok(r) and "permission denied" in r.stderr
    r = as_composer(bed, db_of("A"), "DELETE FROM project.system")
    assert not ok(r) and "permission denied" in r.stderr


@pytest.mark.parametrize("table", ["qualification.qualification", "engine.evaluation",
                                   "control_objectives.project", "controls.submission_answer"])
def test_r7_3_3_composer_never_reads_module_schemas(bed, table):
    """R7.3.3: the composer never reads module schemas; only the renderer does, as report_ro."""
    db = db_of("A")
    assert ok(as_composer(bed, db, "SELECT 1")), "missing feature: report_composer_rw cannot connect"
    r = as_composer(bed, db, f"SELECT 1 FROM {table} LIMIT 1")
    assert not ok(r) and "permission denied" in r.stderr


def test_r7_3_3_composer_reaches_only_its_schema_and_no_comments(bed):
    """R7.3.3, I2.1: the composer connects to project databases (template 0010) but reaches no module schema
    there, and reads nothing of superset's comments."""
    db = db_of("A")
    assert ok(as_composer(bed, db, "SELECT 1")), "I2.1: report_composer_rw cannot connect to a project database"
    for schema in ("qualification", "engine", "control_objectives", "controls", "llm", "provision"):
        assert bed.scalar(db, f"SELECT has_schema_privilege('report_composer_rw', '{schema}', 'USAGE')") == "f", schema
    r = as_composer(bed, "superset", "SELECT 1 FROM public.aisc_comment LIMIT 1")
    assert not ok(r)
