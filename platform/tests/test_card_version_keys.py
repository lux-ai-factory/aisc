"""A card version belongs to its project: core.system is unique on (pid, project_id).

The modules that pin their work to a card version (qualification.qualification,
control_objectives.project, report_composer.layout and generated_report) point at
core.system (pid, project_id), so a row cannot name a version of another project.
That key needs this unique constraint. It is made in three places, each a no-op
when it is already there:

  init/platform-db.sql        fresh volumes, before any module can connect
  init/project-databases.sql  every start of postgres-setup, as the superuser; also
                              adds a module's key when its migration ran first and
                              had to skip it
  migrations/0004             the platform's own record of the change

Each test makes its own scratch database (tests/core_scratch.py).
"""
import psycopg
import pytest

from tests.core_scratch import (
    apply_platform_migrations,
    give_core_system_to_platform,
    needs_superuser,
    project_databases_platform_part,
    scratch_database,
)

pytestmark = needs_superuser

M0004 = "0004_card_version_of_its_project.sql"
UNIQUE = "system_pid_project_id_key"

#: The module keys the superuser adds when a module migration ran before the unique
#: existed: table, constraint, ON DELETE (pg_constraint.confdeltype).
MODULE_KEYS = [
    ("qualification.qualification", "qualification_system_id_project_id_fkey", "c"),
    ("control_objectives.project", "fk_project_system_id_project_id_core_system", "c"),
    ("report_composer.layout", "layout_system_id_project_id_fkey", "a"),
    ("report_composer.generated_report", "generated_report_system_id_project_id_fkey", "a"),
]

STAND_INS = """
CREATE SCHEMA IF NOT EXISTS report_composer;
CREATE TABLE qualification.qualification (id text PRIMARY KEY, project_id uuid NOT NULL, system_id uuid NOT NULL);
CREATE TABLE control_objectives.project (id text PRIMARY KEY, project_id uuid NOT NULL, system_id uuid NOT NULL);
CREATE TABLE report_composer.layout (id text PRIMARY KEY, project_id uuid NOT NULL, system_id uuid NOT NULL);
CREATE TABLE report_composer.generated_report (id text PRIMARY KEY, project_id uuid NOT NULL, system_id uuid NOT NULL);
"""


def _unique_def(dsn):
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "select pg_get_constraintdef(oid) from pg_constraint"
            " where conrelid = 'core.system'::regclass and conname = %s", (UNIQUE,)).fetchone()
    return row[0] if row else None


def _drop_unique(su):
    """The shape of a volume made before this change (the live one)."""
    with psycopg.connect(su, autocommit=True) as conn:
        conn.execute(f"ALTER TABLE core.system DROP CONSTRAINT {UNIQUE}")


def _run_project_databases(su, times=1):
    for _ in range(times):
        with psycopg.connect(su, autocommit=True) as conn:
            conn.execute(project_databases_platform_part())


def _module_keys(su):
    with psycopg.connect(su) as conn:
        return {
            r[0]: (r[1], r[2]) for r in conn.execute(
                "select conname, confdeltype::text, pg_get_constraintdef(oid) from pg_constraint"
                " where contype = 'f' and confrelid = 'core.system'::regclass"
                "   and array_length(conkey, 1) = 2").fetchall()
        }


def _project_with_version(conn, slug):
    project = conn.execute(
        "insert into core.project (name, slug) values (%s, %s) returning pid", (slug, slug)).fetchone()[0]
    numbered = conn.execute(
        "select 1 from information_schema.columns"
        " where table_schema = 'core' and table_name = 'system' and column_name = 'number'").fetchone()
    system = conn.execute(
        "insert into core.system (project_id, name, number) values (%s, 'x', 1) returning pid" if numbered
        else "insert into core.system (project_id, name) values (%s, 'x') returning pid",
        (project,)).fetchone()[0]
    return project, system


# Fresh volumes
def test_init_makes_core_system_unique_on_pid_and_project():
    """Before any migration: a module migrating first on a fresh volume finds it."""
    with scratch_database(old_layout=True) as (su, _rw):
        assert _unique_def(su) == "UNIQUE (pid, project_id)"


def test_0004_on_a_fresh_database_is_recorded_and_leaves_one_constraint():
    with scratch_database(old_layout=True) as (su, rw):
        give_core_system_to_platform(su)
        # up to 0005: the ledger's 0006 needs the schema postgres-setup makes, which these old layouts skip
        ran = apply_platform_migrations(rw, upto="0005")
        assert M0004 in ran
        assert _unique_def(rw) == "UNIQUE (pid, project_id)"
        with psycopg.connect(rw) as conn:
            n = conn.execute(
                "select count(*) from pg_constraint where conrelid = 'core.system'::regclass"
                " and contype = 'u' and pg_get_constraintdef(oid) = 'UNIQUE (pid, project_id)'").fetchone()[0]
        assert n == 1


# The existing (live) shape
def test_0004_adds_the_unique_where_init_did_not():
    with scratch_database(old_layout=True) as (su, rw):
        _drop_unique(su)
        give_core_system_to_platform(su)
        apply_platform_migrations(rw, upto="0003")
        assert _unique_def(rw) is None
        # up to 0004: 0005 (the composer reads members) is not this test's
        assert apply_platform_migrations(rw, upto="0004") == [M0004]
        assert _unique_def(rw) == "UNIQUE (pid, project_id)"


def test_a_key_into_the_pair_refuses_a_version_of_another_project():
    """What the unique is for: a module row naming project A and a version of B fails."""
    with scratch_database(old_layout=True) as (su, rw):
        _drop_unique(su)
        give_core_system_to_platform(su)
        apply_platform_migrations(rw, upto="0005")                   # not the ledger's 0006: see above
        with psycopg.connect(su, autocommit=True) as conn:
            conn.execute(STAND_INS)
            conn.execute(
                "ALTER TABLE qualification.qualification ADD FOREIGN KEY (system_id, project_id)"
                " REFERENCES core.system (pid, project_id)")
            a, _ = _project_with_version(conn, "a")
            _, b_v1 = _project_with_version(conn, "b")
            with pytest.raises(psycopg.errors.ForeignKeyViolation):
                conn.execute("insert into qualification.qualification values ('q', %s, %s)", (a, b_v1))


# Postgres-setup (init/project-databases.sql)
def test_project_databases_adds_the_unique_when_missing_and_is_idempotent():
    with scratch_database(old_layout=True) as (su, _rw):
        _drop_unique(su)
        _run_project_databases(su, times=2)
        assert _unique_def(su) == "UNIQUE (pid, project_id)"


def test_project_databases_skips_module_tables_that_do_not_exist_yet():
    """On a fresh volume it runs before any module has migrated."""
    with scratch_database(old_layout=True) as (su, _rw):
        _run_project_databases(su)
        assert _module_keys(su) == {}


def test_project_databases_adds_the_module_keys_a_module_migration_had_to_skip():
    """A module that migrated before the unique existed: the next start of postgres-setup
    adds its key, with the module's own name and ON DELETE."""
    with scratch_database(old_layout=True) as (su, _rw):
        _drop_unique(su)
        with psycopg.connect(su, autocommit=True) as conn:
            conn.execute(STAND_INS)
        _run_project_databases(su, times=2)
        keys = _module_keys(su)
        assert {name: rule for name, (rule, _def) in keys.items()} == {
            name: rule for _table, name, rule in MODULE_KEYS}
        for _table, name, _rule in MODULE_KEYS:
            assert keys[name][1].startswith(
                "FOREIGN KEY (system_id, project_id) REFERENCES core.system(pid, project_id)")
        with psycopg.connect(su, autocommit=True) as conn:
            a, a_v1 = _project_with_version(conn, "a")
            _, b_v1 = _project_with_version(conn, "b")
            for table, _name, _rule in MODULE_KEYS:
                conn.execute(f"insert into {table} values ('ok', %s, %s)", (a, a_v1))
                with pytest.raises(psycopg.errors.ForeignKeyViolation):
                    conn.execute(f"insert into {table} values ('bad', %s, %s)", (a, b_v1))


def test_project_databases_leaves_a_key_the_module_already_made():
    with scratch_database(old_layout=True) as (su, _rw):
        with psycopg.connect(su, autocommit=True) as conn:
            conn.execute(STAND_INS)
            conn.execute(
                "ALTER TABLE qualification.qualification ADD CONSTRAINT qualification_system_id_project_id_fkey"
                " FOREIGN KEY (system_id, project_id) REFERENCES core.system (pid, project_id) ON DELETE CASCADE")
        _run_project_databases(su)
        names = [n for n in _module_keys(su) if n.startswith("qualification_")]
        assert names == ["qualification_system_id_project_id_fkey"]
