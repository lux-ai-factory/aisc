"""The card versions and the module schemas live in each project's own database.

A missing template file, table or behaviour makes a test fail with a message
that names it.

Runs against the throwaway test database (PLATFORM_TEST_DATABASE_URL, as
platform_rw) and, for the fresh-volume checks, PLATFORM_TEST_SUPERUSER_URL.
"""
from __future__ import annotations

import re
import shutil
import tempfile
import threading
import time
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from platform_service import db, projectdb
from platform_service.migrate import migrate
from tests.conftest import needs_database
from tests.core_scratch import (
    apply_platform_migrations,
    needs_superuser,
    project_databases_platform_part,
    scratch_database,
)

PID = "3f2b8c1e-0d4a-4e7b-9a55-1c2d3e4f5a6b"
ALICE = "00000000-0000-0000-0000-00000000a11c"
BOB = "00000000-0000-0000-0000-0000000000b0"
MALLORY = "00000000-0000-0000-0000-0000000000ma"

OLD_TEMPLATE = ["0001_controls.sql", "0002_dashboard.sql", "0003_report.sql", "0004_inspector.sql", "0005_llm.sql"]
#: The template files that open a project database to a module: which role and schema each one opens.
NEW_TEMPLATE = {
    "0006_project_system.sql": (None, "project"),
    "0007_qualification.sql": ("qualification_rw", "qualification"),
    "0008_control_objectives.sql": ("control_objectives_rw", "control_objectives"),
    "0009_engine.sql": ("engine_rw", "engine"),
    "0010_report_composer.sql": ("report_composer_rw", "report_composer"),
}
MODULE_SCHEMAS = {role: schema for role, schema in NEW_TEMPLATE.values() if role}
#: Who may read and reference the card versions.
VERSION_READERS = ["qualification_rw", "control_objectives_rw", "controls_rw", "engine_rw", "report_composer_rw"]
READERS = ["report_ro", "dashboard_ro"]


# Helpers.


def missing_new_template() -> list[str]:
    return [name for name in NEW_TEMPLATE if not (projectdb.TEMPLATE / name).is_file()]


def require_new_template(req: str) -> None:
    missing = missing_new_template()
    if missing:
        pytest.fail(f"{req}: missing template file(s) platform/project-template/{', '.join(missing)}")


def su_dsn(dsn: str) -> str:
    """The throwaway superuser if given, else the test DSN (platform_rw)."""
    import os

    return os.environ.get("PLATFORM_TEST_SUPERUSER_URL") or dsn


def in_project(dsn: str, pid, *, role: str | None = None) -> psycopg.Connection:
    base = su_dsn(dsn) if role is None else make_conninfo(dsn, user=role, password=role)
    return psycopg.connect(make_conninfo(base, dbname=projectdb.database_name(pid)), autocommit=True)


def role_exists(conn, role: str) -> bool:
    return conn.execute("select 1 from pg_roles where rolname = %s", (role,)).fetchone() is not None


def has_project_system(dsn, pid) -> bool:
    with in_project(dsn, pid) as conn:
        return conn.execute("select to_regclass('project.system')").fetchone()[0] is not None


def require_project_system(dsn, pid, req: str) -> None:
    if not has_project_system(dsn, pid):
        pytest.fail(f"{req}: project.system is missing from {projectdb.database_name(pid)}"
                    " (template 0006_project_system.sql not applied)")


def core_system_rows(dsn, pid) -> int:
    with psycopg.connect(dsn) as conn:
        if conn.execute("select to_regclass('core.system')").fetchone()[0] is None:
            return 0
        return conn.execute("select count(*) from core.system where project_id = %s", (pid,)).fetchone()[0]


def project_system_rows(dsn, pid) -> list[tuple]:
    with in_project(dsn, pid) as conn:
        return conn.execute("select pid, number, name, version from project.system order by number").fetchall()


def insert_version(dsn, pid, number: int, name="MCAS", version="v1") -> str:
    """A card version written straight into the project's database, as platform_rw
    (the only writer). Returns its pid."""
    with in_project(dsn, pid, role="platform_rw") as conn:
        return str(conn.execute(
            "insert into project.system (number, name, version) values (%s, %s, %s) returning pid",
            (number, name, version)).fetchone()[0])


@pytest.fixture
def project(client, as_user, unique):
    response = client.post("/projects", json={"name": unique("iso")}, headers=as_user(ALICE))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture
def other(client, as_user, unique):
    response = client.post("/projects", json={"name": unique("iso-b")}, headers=as_user(BOB))
    assert response.status_code == 201, response.text
    return response.json()


def save(client, as_user, project, who=ALICE, **body):
    body = {"name": "MCAS", "version": "v1.2.0", **body}
    return client.post(f"/projects/{project['slug']}/system-versions", json=body, headers=as_user(who))


# The one rule from a pid to a database name.


@pytest.mark.parametrize("given", [PID, PID.upper(), PID.title()])
def test_i1_8_the_example_pid_names_the_same_database_in_any_case(given):
    """The pid of the shared example names the same database in any letter case."""
    assert projectdb.database_name(given) == "project_3f2b8c1e0d4a4e7b9a551c2d3e4f5a6b"


@pytest.mark.parametrize("bad", [PID.replace("-", ""), "{" + PID + "}", " " + PID, PID[:-1] + "g"])
def test_i1_8_only_the_hyphenated_uuid_form_is_a_pid(bad):
    """Anything that becomes part of a database name must match the uuid regex first."""
    with pytest.raises(projectdb.NotAPid):
        projectdb.database_name(bad)


# The template files, read as text.


@pytest.mark.parametrize("name", list(NEW_TEMPLATE))
def test_i2_1_the_new_template_file_exists_and_is_idempotent_sql(name):
    path = projectdb.TEMPLATE / name
    assert path.is_file(), f"I2.1: missing platform/project-template/{name}"
    text = path.read_text()
    creates = re.findall(r"\bCREATE\s+(?:SCHEMA|TABLE|INDEX|UNIQUE\s+INDEX)\b(?!\s+IF\s+NOT\s+EXISTS)", text, re.I)
    assert creates == [], f"I2.1: CREATE without IF NOT EXISTS in {name}: {creates}"
    assert not re.search(r"^\s*(BEGIN|COMMIT|ROLLBACK)\s*;", text, re.I | re.M), \
        f"I2.1: {name} must run inside the runner's transaction"


@pytest.mark.parametrize("name", [n for n, (role, _s) in NEW_TEMPLATE.items() if role])
def test_i2_1_a_module_file_opens_the_database_and_its_schema_to_its_role_only(name):
    role, schema = NEW_TEMPLATE[name]
    path = projectdb.TEMPLATE / name
    assert path.is_file(), f"I2.1: missing platform/project-template/{name}"
    text = re.sub(r"\s+", " ", path.read_text())
    assert re.search(rf"GRANT CONNECT ON DATABASE %I TO {role}\b", text, re.I), f"I2.1: {name} grants CONNECT to {role}"
    assert re.search(rf"CREATE SCHEMA IF NOT EXISTS {schema}\b", text, re.I)
    assert re.search(rf"GRANT USAGE, CREATE ON SCHEMA {schema} TO {role}\b", text, re.I)
    assert re.search(rf"COMMENT ON SCHEMA {schema}\b", text, re.I)
    assert re.search(rf"ALTER ROLE {role} IN DATABASE %I SET search_path = {schema}\b", text, re.I), \
        f"I2.1: {name} sets {role}'s search_path in this database to {schema} only"
    for reader in READERS:
        assert re.search(rf"GRANT USAGE ON SCHEMA {schema} TO [^;]*\b{reader}\b", text, re.I), \
            f"I2.1: {name} gives {reader} USAGE on {schema} (tables come from the module, I2.6)"
    assert not re.search(r"ALTER DEFAULT PRIVILEGES", text, re.I), \
        "I2.6/D10: reader grants come from the table owner's migrations, never default privileges"


# A new project gets every template file.


@needs_database
def test_i2_4_making_a_project_applies_every_template_file_0001_to_0010(project, dsn):
    with in_project(dsn, project["pid"]) as conn:
        applied = {r[0] for r in conn.execute("select name from provision.template_migration").fetchall()}
    missing = [n for n in OLD_TEMPLATE + list(NEW_TEMPLATE) if n not in applied]
    assert missing == [], f"I2.4/I2.1: provision.template_migration lacks {missing}"


@needs_database
def test_i2_9_a_database_that_had_0001_to_0005_gets_0006_to_0010_at_the_next_provision(project, dsn, monkeypatch):
    """A database made with the old template (only 0001..0005) is brought up to
    date by provision() and by provision_all at the first query after start."""
    # a second project whose database is made from the old template only
    pid = str(uuid.uuid4())
    name = projectdb.database_name(pid)
    old = Path(tempfile.mkdtemp(prefix="pytest-old-template-"))
    try:
        for f in OLD_TEMPLATE:
            shutil.copy(projectdb.TEMPLATE / f, old / f)
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(f'create database "{name}"')
        with psycopg.connect(make_conninfo(dsn, dbname=name)) as conn:
            migrate(conn, old, projectdb.TRACKING_TABLE)
        projectdb.provision(dsn, pid)
        with psycopg.connect(make_conninfo(dsn, dbname=name)) as conn:
            applied = {r[0] for r in conn.execute("select name from provision.template_migration").fetchall()}
            system = conn.execute("select to_regclass('project.system')").fetchone()[0]
        missing = [n for n in NEW_TEMPLATE if n not in applied]
        assert missing == [], f"I2.9: an existing database did not get {missing}"
        assert system is not None, "I2.9: project.system missing after provision()"
    finally:
        shutil.rmtree(old, ignore_errors=True)
        projectdb.drop(dsn, pid)

    # and the same through provision_all, for the fixture's project, whose new
    # rows are removed as if it predated 0006
    with in_project(dsn, project["pid"]) as conn:
        conn.execute("delete from provision.template_migration where name = any(%s)", (list(NEW_TEMPLATE),))
    monkeypatch.setattr(db, "_unprovisioned", None)
    db.pool()
    with in_project(dsn, project["pid"]) as conn:
        applied = {r[0] for r in conn.execute("select name from provision.template_migration").fetchall()}
    missing = [n for n in NEW_TEMPLATE if n not in applied]
    assert missing == [], f"I2.9: provision_all did not bring the project to {missing}"


# project.system


@needs_database
def test_i1_5_project_system_has_exactly_the_card_version_columns(project, dsn):
    require_project_system(dsn, project["pid"], "I1.5")
    with in_project(dsn, project["pid"]) as conn:
        cols = {r[0]: (r[1], r[2], r[3]) for r in conn.execute(
            "select column_name, data_type, is_nullable, column_default from information_schema.columns"
            " where table_schema = 'project' and table_name = 'system'").fetchall()}
        owner = conn.execute("select pg_get_userbyid(relowner) from pg_class where oid = 'project.system'::regclass"
                             ).fetchone()[0]
        pk = conn.execute(
            "select array_agg(a.attname::text) from pg_index i join pg_attribute a on a.attrelid = i.indrelid"
            " and a.attnum = any(i.indkey) where i.indrelid = 'project.system'::regclass and i.indisprimary"
        ).fetchone()[0]
        unique_number = conn.execute(
            "select 1 from pg_index i join pg_attribute a on a.attrelid = i.indrelid and a.attnum = any(i.indkey)"
            " where i.indrelid = 'project.system'::regclass and i.indisunique and i.indnatts = 1"
            " and a.attname = 'number'").fetchone()
    assert set(cols) == {"pid", "number", "name", "version", "provider", "description",
                         "created_at", "updated_at", "created_by"}, f"I1.5: columns are {sorted(cols)}"
    assert "project_id" not in cols, "I1.5/I1.7: project.system has no project_id: the database is the project"
    assert cols["pid"][0] == "uuid" and "gen_random_uuid" in (cols["pid"][2] or "")
    assert cols["number"][:2] == ("integer", "NO")
    assert cols["name"][:2] == ("text", "NO")
    for c in ("version", "provider", "description", "created_by"):
        assert cols[c][:2] == ("text", "YES"), c
    for c in ("created_at", "updated_at"):
        assert cols[c][:2] == ("timestamp with time zone", "NO") and "now()" in (cols[c][2] or ""), c
    assert pk == ["pid"]
    assert unique_number, "I1.5: number is UNIQUE"
    assert owner == "platform_rw", "I1.5/I2.1: project.system is owned by platform_rw"


@needs_database
def test_i1_5_number_must_be_positive(project, dsn):
    require_project_system(dsn, project["pid"], "I1.5")
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_version(dsn, project["pid"], 0)


@needs_database
def test_i1_5_only_the_latest_version_may_change_and_no_number_ever_changes(project, dsn):
    require_project_system(dsn, project["pid"], "I1.5")
    first = insert_version(dsn, project["pid"], 1)
    second = insert_version(dsn, project["pid"], 2)
    with in_project(dsn, project["pid"], role="platform_rw") as conn:
        conn.execute("update project.system set description = 'fine' where pid = %s", (second,))
        with pytest.raises(psycopg.Error, match="(?i)latest|number|change"):
            conn.execute("update project.system set description = 'no' where pid = %s", (first,))
        with pytest.raises(psycopg.Error, match="(?i)latest|number|change"):
            conn.execute("update project.system set number = 3 where pid = %s", (second,))
        trigger = conn.execute("select 1 from pg_trigger where tgrelid = 'project.system'::regclass"
                               " and tgname = 'system_only_latest_changes'").fetchone()
    assert trigger, "I1.5: trigger project.system_only_latest_changes"


# Who may do what in a project database.


@needs_database
def test_i2_1_only_platform_rw_writes_project_system_and_the_modules_read_and_reference_it(project, dsn):
    require_project_system(dsn, project["pid"], "I2.1")
    with in_project(dsn, project["pid"]) as conn:
        for role in VERSION_READERS + READERS:
            if not role_exists(conn, role):
                continue
            usage = conn.execute("select has_schema_privilege(%s, 'project', 'USAGE')", (role,)).fetchone()[0]
            select = conn.execute("select has_table_privilege(%s, 'project.system', 'SELECT')", (role,)).fetchone()[0]
            assert usage and select, f"I2.1: {role} has USAGE on project and SELECT on project.system"
            refs = conn.execute("select has_table_privilege(%s, 'project.system', 'REFERENCES')", (role,)).fetchone()[0]
            assert refs is (role in VERSION_READERS), f"I2.1: REFERENCES on project.system for {role} is {refs}"
            for priv in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                granted = conn.execute("select has_table_privilege(%s, 'project.system', %s)", (role, priv)).fetchone()[0]
                assert granted is False, f"I2.1: {role} must not {priv} project.system"
    with in_project(dsn, project["pid"], role="qualification_rw") as conn, \
            pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute("insert into project.system (number, name) values (1, 'x')")


@needs_database
@pytest.mark.parametrize("role", list(MODULE_SCHEMAS))
def test_i1_2_a_module_role_connects_and_has_its_own_schema_only(project, dsn, role):
    """Each module's schema exists in the project database, owned by
    platform_rw, and only that module's role may create in it."""
    require_new_template("I1.2")
    own = MODULE_SCHEMAS[role]
    with in_project(dsn, project["pid"]) as conn:
        owner, comment = conn.execute(
            "select pg_get_userbyid(nspowner), obj_description(oid, 'pg_namespace') from pg_namespace"
            " where nspname = %s", (own,)).fetchone() or (None, None)
        assert owner == "platform_rw", f"I1.2: schema {own} owned by platform_rw (D10), got {owner}"
        assert comment, f"I2.1: schema {own} has a comment"
        for schema in ["controls", "llm", "connection", "provision", *MODULE_SCHEMAS.values()]:
            if conn.execute("select 1 from pg_namespace where nspname = %s", (schema,)).fetchone() is None:
                continue
            usage = conn.execute("select has_schema_privilege(%s, %s, 'USAGE')", (role, schema)).fetchone()[0]
            create = conn.execute("select has_schema_privilege(%s, %s, 'CREATE')", (role, schema)).fetchone()[0]
            if schema == own:
                assert usage and create, f"I1.2: {role} has USAGE, CREATE on {own}"
            else:
                assert not usage and not create, f"I1.4/I16.1: {role} has rights on {schema}"
        setting = conn.execute(
            "select array_to_string(s.setconfig, ',') from pg_db_role_setting s"
            " join pg_database d on d.oid = s.setdatabase join pg_roles r on r.oid = s.setrole"
            " where d.datname = current_database() and r.rolname = %s", (role,)).fetchone()
    assert setting and re.search(rf"search_path={own}\b", setting[0]), \
        f"I2.1: ALTER ROLE {role} IN DATABASE ... SET search_path = {own}; got {setting}"
    # the role can really connect, and an unqualified name lands in its own schema
    with in_project(dsn, project["pid"], role=role) as conn:
        conn.execute("create table probe_i1_2 (x int)")
        where = conn.execute("select n.nspname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
                             " where c.relname = 'probe_i1_2'").fetchone()[0]
        conn.execute("drop table probe_i1_2")
    assert where == own


@needs_database
def test_i1_6_a_module_may_point_a_foreign_key_at_project_system(project, dsn):
    """REFERENCES lets each module recreate its FK on project.system(pid)."""
    require_new_template("I1.6")
    with in_project(dsn, project["pid"], role="qualification_rw") as conn:
        conn.execute("create table qualification.probe_i1_6 (s uuid references project.system (pid) on delete cascade)")
        conn.execute("drop table qualification.probe_i1_6")
    with in_project(dsn, project["pid"], role="engine_rw") as conn:
        conn.execute("create table engine.probe_i1_6 (s uuid references project.system (pid) on delete set null)")
        conn.execute("drop table engine.probe_i1_6")


@needs_database
def test_i2_1_readers_get_usage_on_every_module_schema(project, dsn):
    require_new_template("I2.1")
    with in_project(dsn, project["pid"]) as conn:
        for reader in READERS:
            if not role_exists(conn, reader):
                continue
            for schema in [*MODULE_SCHEMAS.values(), "project"]:
                usage = conn.execute("select has_schema_privilege(%s, %s, 'USAGE')", (reader, schema)).fetchone()[0]
                assert usage, f"I2.1: {reader} has USAGE on {schema}"
            for schema in ("llm", "connection", "provision"):
                usage = conn.execute("select has_schema_privilege(%s, %s, 'USAGE')", (reader, schema)).fetchone()[0]
                assert not usage, f"I2.6: {reader} has USAGE on {schema}"


@needs_database
def test_i18_5_no_module_role_or_reader_reaches_llm_once_every_module_may_connect(project, dsn):
    """With 0006..0010 every module role connects; still none of them, nor a
    reader, has any right on llm.* (the keys)."""
    require_new_template("I18.5")
    with in_project(dsn, project["pid"]) as conn:
        for role in [*MODULE_SCHEMAS, "controls_rw", *READERS]:
            if not role_exists(conn, role):
                continue
            assert not conn.execute("select has_schema_privilege(%s, 'llm', 'USAGE')", (role,)).fetchone()[0], role
            for table in ("llm.provider", "llm.system_choice"):
                assert not conn.execute("select has_table_privilege(%s, %s, 'SELECT')", (role, table)).fetchone()[0], \
                    f"I18.5: {role} reads {table}"


# The card-version functions use project.system.


@needs_database
def test_i2_2_saving_a_version_writes_project_system_of_that_project_only(client, as_user, project, other, dsn):
    require_project_system(dsn, project["pid"], "I2.2")
    before = core_system_rows(dsn, project["pid"])
    first = save(client, as_user, project)
    second = save(client, as_user, project)
    assert first.status_code == 201 and second.status_code == 201, (first.text, second.text)
    rows = project_system_rows(dsn, project["pid"])
    assert [(str(r[0]), r[1]) for r in rows] == [(first.json()["pid"], 1), (second.json()["pid"], 2)], \
        "I2.2: saves land in project.system of the project's database"
    assert core_system_rows(dsn, project["pid"]) == before, "I2.2: core.system is never written again"
    assert project_system_rows(dsn, other["pid"]) == [], "I2.2: another project's database is untouched"
    assert first.json()["project_id"] == project["pid"], "I2.2: responses keep project_id, filled from core.project"


@needs_database
def test_i2_2_list_and_latest_read_project_system(client, as_user, project, dsn):
    require_project_system(dsn, project["pid"], "I2.2")
    one = insert_version(dsn, project["pid"], 1, version="a")
    two = insert_version(dsn, project["pid"], 2, version="b")
    listed = client.get(f"/projects/{project['slug']}/system-versions", headers=as_user(ALICE))
    latest = client.get(f"/projects/{project['slug']}/system-versions/latest", headers=as_user(ALICE))
    assert listed.status_code == 200 and latest.status_code == 200
    assert [v["pid"] for v in listed.json()] == [two, one], "I2.2: list_versions reads project.system"
    assert latest.json()["pid"] == two and latest.json()["number"] == 2
    assert latest.json()["project_id"] == project["pid"]


@needs_database
def test_i2_2_two_saves_at_once_get_n_and_n_plus_1_in_the_project_database(client, as_user, project, dsn):
    require_project_system(dsn, project["pid"], "I2.2")
    results, barrier = [], threading.Barrier(2)

    def one():
        barrier.wait()
        results.append(save(client, as_user, project))

    threads = [threading.Thread(target=one) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.status_code for r in results) == [201, 201]
    assert sorted(r[1] for r in project_system_rows(dsn, project["pid"])) == [1, 2]


# GET /systems/{pid} scans only the caller's projects.


@needs_database
def test_i2_3_a_non_uuid_is_404(client, as_user):
    for bad in ("not-a-uuid", "1", PID + "x"):
        assert client.get(f"/systems/{bad}", headers=as_user(ALICE)).status_code == 404, bad


@needs_database
def test_i2_3_a_version_is_found_in_the_callers_project_database(client, as_user, project, other, dsn):
    require_project_system(dsn, project["pid"], "I2.3")
    mine = insert_version(dsn, project["pid"], 1)
    theirs = insert_version(dsn, other["pid"], 1)
    got = client.get(f"/systems/{mine}", headers=as_user(ALICE))
    assert got.status_code == 200, "I2.3: found in the caller's project database"
    assert got.json()["project_id"] == project["pid"] and got.json()["number"] == 1
    assert client.get(f"/systems/{theirs}", headers=as_user(ALICE)).status_code == 404, \
        "I2.3: a version of a project the caller is not in is 404"
    assert client.get(f"/systems/{mine}", headers=as_user(MALLORY)).status_code == 404
    admin = {"Authorization": as_user("root", roles=("admin",))["Authorization"]}
    assert client.get(f"/systems/{theirs}", headers=admin).status_code == 200, "I2.3: an admin sees every project"
    assert client.get(f"/systems/{uuid.uuid4()}", headers=admin).status_code == 404


# Deleting a project: the order of the steps, and a dropped database answers 404.


@needs_database
def test_i2_5_delete_unregisters_then_drops_then_deletes_the_row(client, as_user, project, monkeypatch):
    """Deleting a project unregisters it, drops its database, then deletes its row, in that order."""
    from platform_service import app as app_module

    calls = []
    real_drop, real_delete = projectdb.drop, db.delete_project
    monkeypatch.setattr(app_module.dashboard_bridge, "unregister", lambda pid: calls.append("unregister") or True)
    monkeypatch.setattr(projectdb, "drop", lambda dsn_, pid: (calls.append("drop"), real_drop(dsn_, pid))[1])
    monkeypatch.setattr(db, "delete_project", lambda pid: (calls.append("delete"), real_delete(pid))[1])
    admin = as_user("root", roles=("admin",))
    response = client.request("DELETE", f"/projects/{project['slug']}",
                              json={"confirm_name": project["name"]}, headers=admin)
    assert response.status_code == 204
    assert calls == ["unregister", "drop", "delete"]


@needs_database
def test_i2_5_versions_of_a_project_whose_database_is_gone_are_404_not_500(client, as_user, project, dsn):
    """Between DROP DATABASE and the core.project delete, the card-version
    routes answer 404 for that pid (the database is the project)."""
    projectdb.drop(dsn, project["pid"])
    for path in (f"/projects/{project['slug']}/system-versions",
                 f"/projects/{project['slug']}/system-versions/latest"):
        got = client.get(path, headers=as_user(ALICE))
        assert got.status_code == 404, f"I2.5: {path} answered {got.status_code} with the database dropped"
    assert save(client, as_user, project).status_code == 404


# One connection per call to a project database.


@needs_database
def test_i17_1_the_platform_opens_the_project_database_per_call_and_closes_it(client, as_user, project, dsn):
    name = projectdb.database_name(project["pid"])

    def sessions():
        with psycopg.connect(su_dsn(dsn), autocommit=True) as conn:
            conn.execute("select pg_stat_clear_snapshot()")
            return conn.execute("select coalesce(sessions, 0) from pg_stat_database where datname = %s",
                                (name,)).fetchone()[0]

    time.sleep(1.0)
    before = sessions()
    save(client, as_user, project)
    client.get(f"/projects/{project['slug']}/system-versions", headers=as_user(ALICE))
    deadline, after = time.monotonic() + 5, before
    while time.monotonic() < deadline and after == before:
        time.sleep(0.5)
        after = sessions()
    assert after > before, f"I17.1/I2.2: the card-version calls never opened {name}"
    with psycopg.connect(su_dsn(dsn), autocommit=True) as conn:
        lingering = conn.execute("select count(*) from pg_stat_activity where datname = %s"
                                 " and usename = 'platform_rw'", (name,)).fetchone()[0]
    assert lingering == 0, "I17.1: no pooled platform_rw session stays open on a project database"


# The diagrams gate covers the project database schemas.


@needs_database
def test_i11_2_a_member_sees_the_new_schemas_of_their_project_and_a_stranger_does_not(client, as_user, project):
    """A member sees the schemas of their project's database and a stranger does not (more in test_authz_schema.py)."""
    database = projectdb.database_name(project["pid"])
    for schema in ("project", "qualification", "control_objectives", "engine", "report_composer"):
        uri = f"/{database}/{schema}/index.html"
        assert client.get("/authz/schema", headers={**as_user(ALICE), "X-Forwarded-Uri": uri}).status_code == 204
        assert client.get("/authz/schema", headers={**as_user(MALLORY), "X-Forwarded-Uri": uri}).status_code == 403


# A fresh platform database.


def _setup_part(su: str) -> None:
    with psycopg.connect(su, autocommit=True) as conn:
        conn.execute(project_databases_platform_part())


def _fresh_platform(su: str, rw: str) -> None:
    """The order of a real fresh volume: init/platform-db.sql (scratch_database),
    postgres-setup (init/project-databases.sql) before the platform starts, the
    platform's migrations at its first query, and postgres-setup again at the
    next start."""
    _setup_part(su)
    apply_platform_migrations(rw)
    _setup_part(su)


@needs_superuser
def test_i2_8_a_fresh_platform_database_has_no_module_schema_and_no_core_system():
    """init/platform-db.sql, the platform migrations and
    init/project-databases.sql on an empty database leave only the shared schemas."""
    with scratch_database() as (su, rw):
        _fresh_platform(su, rw)
        with psycopg.connect(su) as conn:
            schemas = {r[0] for r in conn.execute(
                "select nspname from pg_namespace where nspname !~ '^pg_' and nspname <> 'information_schema'"
            ).fetchall()}
            core = {r[0] for r in conn.execute(
                "select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
                " where n.nspname = 'core' and c.relkind in ('r', 'p')").fetchall()}
            owners = dict(conn.execute("select nspname, pg_get_userbyid(nspowner) from pg_namespace"
                                       " where nspname in ('form_library', 'report_library')").fetchall())
    assert not schemas & {"qualification", "control_objectives", "engine", "report_composer"}, \
        f"I2.8: platform-db.sql still makes module schemas: {sorted(schemas)}"
    # core.outbox is the platform's own ledger outbox (migration 0008), not a module's table
    assert core == {"project", "project_member", "schema_migration", "outbox"}, f"I1.3: core has {sorted(core)}"
    # (forms are per project: there is no form library in platform)
    assert "form_library" not in schemas and "report_library" in schemas, "I2.8: report_library only"
    assert owners.get("report_library") == "report_composer_rw", "I1.4: report_composer_rw owns report_library"


@needs_superuser
def test_i2_8_project_databases_sql_still_runs_once_core_system_is_gone():
    """Once core.system is dropped, the core.system owner line and the composite-key
    block of init/project-databases.sql run only when core.system exists."""
    with scratch_database() as (su, rw):
        # the current layout first (the setup hands core.system over, then migrate),
        # then core.system is dropped, then the setup of the next start runs
        _setup_part(su)
        apply_platform_migrations(rw)
        with psycopg.connect(su, autocommit=True) as conn:
            conn.execute("drop table if exists core.system cascade")
            conn.execute("drop function if exists core.system_only_latest_changes() cascade")
            try:
                conn.execute(project_databases_platform_part())
            except psycopg.Error as exc:
                pytest.fail(f"I2.8: init/project-databases.sql fails without core.system: {type(exc).__name__}")


MODULE_ROLES_IN_PLATFORM = ["qualification_rw", "control_objectives_rw", "engine_rw", "controls_rw", "report_composer_rw"]


@needs_superuser
def test_i1_4_a_module_role_reads_only_project_and_project_member_in_platform():
    with scratch_database() as (su, rw):
        _fresh_platform(su, rw)
        with psycopg.connect(su) as conn:
            own = {"report_composer_rw": "report_library"}
            schemas = [r[0] for r in conn.execute(
                "select nspname from pg_namespace where nspname !~ '^pg_'"
                " and nspname not in ('information_schema', 'public')").fetchall()]
            for role in MODULE_ROLES_IN_PLATFORM:
                if not role_exists(conn, role):
                    continue
                for schema in schemas:
                    usage = conn.execute("select has_schema_privilege(%s, %s, 'USAGE')", (role, schema)).fetchone()[0]
                    expected = schema == "core" or own.get(role) == schema
                    assert usage is expected, f"I1.4: {role} USAGE on {schema} is {usage}"
                for table, sel in (("core.project", True), ("core.project_member", True), ("core.schema_migration", False)):
                    got = conn.execute("select has_table_privilege(%s, %s, 'SELECT')", (role, table)).fetchone()[0]
                    assert got is sel, f"I1.4: {role} SELECT {table} is {got}"
                    for priv in ("INSERT", "UPDATE", "DELETE", "REFERENCES"):
                        assert not conn.execute("select has_table_privilege(%s, %s, %s)",
                                                (role, table, priv)).fetchone()[0], f"I1.4: {role} {priv} {table}"
            if role_exists(conn, "dashboard_ro"):
                assert conn.execute("select has_table_privilege('dashboard_ro', 'core.project_member', 'SELECT')").fetchone()[0]
                assert not conn.execute("select has_table_privilege('dashboard_ro', 'core.project', 'SELECT')").fetchone()[0], \
                    "I1.4: dashboard_ro keeps only SELECT core.project_member"
                defaults = conn.execute("select count(*) from pg_default_acl d join pg_roles r on r.oid = d.defaclrole"
                                        " where array_to_string(d.defaclacl, ',') like '%dashboard_ro%'").fetchone()[0]
                assert defaults == 0, "I2.8: platform-db.sql no longer gives dashboard_ro default privileges"
