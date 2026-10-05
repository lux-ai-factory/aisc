"""Grants inside a project database.

Two throwaway project databases (A and B) made by the platform's own provision, then every module's
own migrate command (scripts/tests/isolation_bed.py). When a step of the bed fails, it records what is
missing and each test that needs it fails naming it.

    uv run --no-project --with pytest --with 'psycopg[binary]' python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_project_grants.py
"""

from __future__ import annotations

import sys

import pytest

import isolation_bed as ib
from conftest import ROOT

sys.path.insert(0, str(ROOT / "scripts/lib"))
import report_bed  # noqa: E402

ALL_MODULES = ("templates", "project_system", "qualification", "control_objectives", "engine",
               "report_composer", "controls")
DBS = [ib.project_db(ib.A), ib.project_db(ib.B)]


@pytest.fixture(scope="module")
def bed():
    b = ib.build("grants")
    yield b
    b.stop()


def _tables(bed, db, schema):
    return [r["relname"] for r in bed.rows(db, f"""
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = '{schema}' AND c.relkind IN ('r', 'p', 'v') ORDER BY 1""")]


def _can(bed, db, role, rel, priv="SELECT") -> bool:
    return bed.scalar(db, f"SELECT has_table_privilege('{role}', '{rel}', '{priv}')") == "t"


# template files and search paths


def test_i2_1_every_project_database_lists_template_0001_to_0010(bed):
    """Provision applies template files 0001 to 0010 in order, tracked in provision.template_migration."""
    bed.require("templates", "provision")
    for db in DBS:
        names = [r["name"] for r in bed.rows(db, "SELECT name FROM provision.template_migration ORDER BY 1")]
        assert names == ib.TEMPLATES, f"{db}: {names}"


@pytest.mark.parametrize("schema", ["project", "qualification", "control_objectives", "engine", "report_composer"])
def test_i2_1_the_template_makes_each_module_schema_owned_by_platform_rw(bed, schema):
    """Each module schema is created by the template and owned by platform_rw."""
    bed.require("templates")
    for db in DBS:
        owner = bed.scalar(db, f"SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = '{schema}'")
        assert owner == "platform_rw", f"I2.1: {db} schema {schema} owner is {owner!r}"


@pytest.mark.parametrize("schema,role", [(s, r) for s, r in ib.MODULES.items() if s != "controls"])
def test_i2_1_each_module_role_has_its_own_search_path_in_the_project_database(bed, schema, role):
    """ALTER ROLE <module role> IN DATABASE <db> SET search_path = <module>."""
    bed.require("templates")
    for db in DBS:
        cfg = bed.scalar(db, f"""
            SELECT array_to_string(s.setconfig, ',') FROM pg_db_role_setting s
              JOIN pg_database d ON d.oid = s.setdatabase JOIN pg_roles r ON r.oid = s.setrole
             WHERE d.datname = current_database() AND r.rolname = '{role}'""")
        assert f"search_path={schema}" in cfg, f"I2.1: {db} {role} settings {cfg!r}"


# the reader list, exhaustive


@pytest.mark.parametrize("reader", ib.READERS)
@pytest.mark.parametrize("schema", sorted(ib.READER_TABLES))
def test_i2_6_readers_see_exactly_the_listed_tables(bed, reader, schema):
    """In every project database, SELECT for report_ro and dashboard_ro on exactly the
    tables of the reader list, no more, no less (engine.aisc_backend_pluginconfig is checked by column below)."""
    bed.require(*ALL_MODULES)
    for db in DBS:
        present = _tables(bed, db, schema)
        listed = ib.READER_TABLES[schema]
        absent = [t for t in listed if t not in present]
        assert not absent, f"I2.6: {db} lacks listed tables {schema}.{absent}"
        wrong = []
        for t in present:
            if schema == "engine" and t == "aisc_backend_pluginconfig":
                continue
            want = t in listed
            got = _can(bed, db, reader, f"{schema}.{t}")
            if want != got:
                wrong.append(f"{schema}.{t} want {want} got {got}")
        assert not wrong, f"I2.6: {db} {reader}: {wrong}"


@pytest.mark.parametrize("reader", ib.READERS)
def test_i2_6_engine_plugin_config_only_its_id_and_plugin_id_columns(bed, reader):
    """`plugin_config (id, plugin_id)` columns only; `config` never."""
    bed.require("engine")
    for db in DBS:
        assert not _can(bed, db, reader, "engine.aisc_backend_pluginconfig"), f"{db}: table-wide SELECT on plugin_config"
        for col in ib.PLUGIN_CONFIG_COLUMNS:
            assert bed.scalar(db, f"SELECT has_column_privilege('{reader}', 'engine.aisc_backend_pluginconfig',"
                                  f" '{col}', 'SELECT')") == "t"
        assert bed.scalar(db, f"SELECT has_column_privilege('{reader}', 'engine.aisc_backend_pluginconfig',"
                              " 'config', 'SELECT')") == "f"


@pytest.mark.parametrize("reader", ib.READERS)
@pytest.mark.parametrize("rel", ib.SECRETS)
def test_i2_6_secrets_are_unreadable_by_readers(bed, reader, rel):
    """engine.aisc_backend_projectconfig, plugin_config_project_config and llm.* are never readable."""
    bed.require(*ALL_MODULES)
    for db in DBS:
        assert bed.exists(db, rel), f"I2.6: {db} lacks {rel}"
        assert not _can(bed, db, reader, rel), f"I2.6: {reader} can read {rel} in {db}"


@pytest.mark.parametrize("reader", ib.READERS)
def test_i2_6_readers_never_write(bed, reader):
    """No INSERT, UPDATE, DELETE or TRUNCATE for a reader on any table of a project database."""
    bed.require(*ALL_MODULES)
    for db in DBS:
        rows = bed.rows(db, f"""
            SELECT n.nspname || '.' || c.relname AS rel FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE c.relkind IN ('r', 'p') AND n.nspname NOT IN ('pg_catalog', 'information_schema')
               AND (has_table_privilege('{reader}', c.oid, 'INSERT') OR has_table_privilege('{reader}', c.oid, 'UPDATE')
                    OR has_table_privilege('{reader}', c.oid, 'DELETE') OR has_table_privilege('{reader}', c.oid, 'TRUNCATE'))""")
        assert rows == [], f"{db}: {reader} may write {rows}"


def test_i2_6_no_default_privilege_grants_to_a_reader(bed):
    """Reader grants come from each table owner's migration path, never from a default privilege
    (which would also cover secrets)."""
    bed.require(*ALL_MODULES)
    for db in DBS:
        rows = bed.rows(db, """
            SELECT pg_get_userbyid(defaclrole) AS owner, defaclnamespace::regnamespace::text AS schema,
                   array_to_string(defaclacl, ',') AS acl FROM pg_default_acl""")
        bad = [r for r in rows if "report_ro=" in r["acl"] or "dashboard_ro=" in r["acl"]]
        assert bad == [], f"{db}: default privileges to readers {bad}"


# module roles: their own schema, project.system read-only, nothing else


@pytest.mark.parametrize("schema,role", list(ib.MODULES.items()))
def test_i16_1_a_module_role_has_rights_only_on_its_own_schema(bed, schema, role):
    """USAGE, CREATE on its own schema; USAGE on project; nothing on llm, provision or another
    module's schema."""
    bed.require(*ALL_MODULES)
    for db in DBS:
        assert bed.scalar(db, f"SELECT has_schema_privilege('{role}', '{schema}', 'USAGE')") == "t"
        assert bed.scalar(db, f"SELECT has_schema_privilege('{role}', 'project', 'USAGE')") == "t"
        for other in [*ib.MODULES, "llm", "connection", "provision"]:
            if other == schema:
                continue
            for priv in ("USAGE", "CREATE"):
                got = bed.scalar(db, f"SELECT has_schema_privilege('{role}', '{other}', '{priv}')")
                assert got == "f", f"I16.1: {db} {role} has {priv} on {other}"


@pytest.mark.parametrize("role", list(ib.MODULES.values()))
def test_i2_1_project_system_is_select_and_references_only_for_module_roles(bed, role):
    """SELECT, REFERENCES on project.system for every module role; no role but platform_rw writes it."""
    bed.require("templates", "project_system")
    for db in DBS:
        assert _can(bed, db, role, "project.system", "SELECT")
        assert _can(bed, db, role, "project.system", "REFERENCES")
        for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert not _can(bed, db, role, "project.system", priv), f"I2.1: {db} {role} may {priv} project.system"
        owner = bed.scalar(db, "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'project.system'::regclass")
        assert owner == "platform_rw"


@pytest.mark.parametrize("schema,role", [(s, r) for s, r in ib.MODULES.items()])
def test_i2_6_module_tables_are_owned_by_their_module_role(bed, schema, role):
    """Tables of a module schema are created by its own migrations, owned by its role."""
    bed.require(*ALL_MODULES)
    for db in DBS:
        rows = bed.rows(db, f"""
            SELECT c.relname, pg_get_userbyid(c.relowner) AS owner FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = '{schema}' AND c.relkind IN ('r', 'p')""")
        assert rows, f"{db}: no tables in {schema}"
        assert {r["owner"] for r in rows} == {role}, f"{db} {schema}: {rows}"


# inspector_ro


@pytest.mark.parametrize("schema", ["project", "qualification", "control_objectives", "engine", "report_composer"])
def test_i11_1_inspector_reads_every_new_schema_and_writes_nothing(bed, schema):
    """inspector_ro SELECTs a row from each schema of a project database and cannot INSERT."""
    bed.require(*ALL_MODULES)
    db = DBS[0]
    tables = _tables(bed, db, schema)
    assert tables, f"I11.1: no table in {db}.{schema}"
    for t in tables:
        r = bed.psql(db, f"SELECT * FROM {schema}.{t} LIMIT 1", role="inspector_ro")
        assert r.returncode == 0, f"I11.1: inspector_ro cannot read {schema}.{t}: {r.stderr.strip()[-200:]}"
    r = bed.psql(db, "INSERT INTO project.system (number, name) VALUES (99, 'probe')", role="inspector_ro")
    assert r.returncode != 0, "I11.1: inspector_ro inserted into project.system"


# scripts/report-grants.sh, the superuser repair one-shot


GRANTS_SH = ROOT / "scripts/report-grants.sh"


def test_i2_7_report_grants_has_no_platform_section_for_moved_schemas():
    """There is no platform section for qualification, control_objectives or engine: those live in
    the project databases."""
    text = GRANTS_SH.read_text()
    assert "engine.aisc_backend_measurement" not in text, "I2.7: report-grants.sh still waits for platform engine.aisc_backend_measurement"
    assert "-d platform -f" not in text, "I2.7: report-grants.sh still applies report-ro-grants.sql to platform"


def test_i2_7_report_grants_covers_every_module_schema_of_a_project_database():
    """The per-project loop grants the whole reader list (project, controls, qualification,
    control_objectives, engine), not only controls."""
    text = GRANTS_SH.read_text()
    for schema in ("project", "qualification", "control_objectives", "engine"):
        assert f"'{schema}'" in text or f"{schema}." in text, f"I2.7: report-grants.sh does not grant {schema}"
    assert "dashboard_ro" in text, "I2.7: report-grants.sh does not repair dashboard_ro"


def test_i2_7_report_grants_repairs_a_revoked_grant_and_reruns_idempotently(bed):
    """After a reader grant is revoked, one run restores it; a second run exits 0 and changes nothing;
    secrets stay unreadable."""
    bed.require(*ALL_MODULES)
    db = DBS[0]
    bed.psql(db, "REVOKE SELECT ON qualification.qualification FROM report_ro, dashboard_ro;"
                 "REVOKE SELECT ON engine.aisc_backend_evaluation FROM report_ro, dashboard_ro")
    r = report_bed.run_report_grants(bed.t)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
    assert bed.t.password not in r.stdout + r.stderr
    for reader in ib.READERS:
        assert _can(bed, db, reader, "qualification.qualification"), f"I2.7: {reader} not repaired"
        assert _can(bed, db, reader, "engine.aisc_backend_evaluation"), f"I2.7: {reader} not repaired"
        assert not _can(bed, db, reader, "engine.aisc_backend_projectconfig")
    again = report_bed.run_report_grants(bed.t)
    assert again.returncode == 0, (again.stdout + again.stderr)[-1500:]


def test_i2_7_report_grants_skips_a_project_database_without_module_tables(bed):
    """A project database with only the template (no module migrated yet) is skipped table by table,
    and the run still exits 0."""
    bed.require("templates")
    extra = "c0000000-0000-4000-8000-00000000000c"
    ib.provision(bed, [extra])
    bed.require("provision")
    r = report_bed.run_report_grants(bed.t)
    assert r.returncode == 0, (r.stdout + r.stderr)[-1500:]
