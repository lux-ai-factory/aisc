"""Every module schema in a project database belongs to its owner role; the runtime role keeps DML only.

A bed made as postgres-setup, the platform and each module's own migrate command make a stack
(owner_roles_bed). Qualification, controls, control objectives and the report composer each run their
migrations as their owner (through the migrator login), so:
- their tables belong to `<module>_owner`, and the role the app connects as cannot create, alter,
  truncate or put triggers on them, nor lift a guard;
- on the append-only tables the runtime role may only insert and read;
- a reference to a card version restricts its deletion instead of cascading or doing nothing;
- not even a migration can lift a guard that keeps a closed card version as it was;
- a module migration on a database whose schema has no owner role stops and names postgres-setup.

    cd scripts/tests && uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' \
        pytest -q -p no:cacheprovider test_module_owner_roles.py
"""

from __future__ import annotations

import pytest

import isolation_bed as ib
import owner_roles_bed as ob

DB = ib.project_db(ib.A)
MODULES = ("qualification", "controls", "control_objectives", "report_composer")

#: module schema -> its tables on which the runtime role may only insert and read.
APPEND_ONLY = {
    "qualification": ("card_history", "question_set_version", "question_set_version_item",
                      "questionnaire_version", "questionnaire_version_item"),
    "control_objectives": ("mapping_archive",),
    "report_composer": ("layout_revision",),
}

#: (module, a guard trigger of that module on table) that the runtime role and the migrator must not lift.
GUARDS = [
    ("qualification", "qualification.card_history", "card_history_is_append_only"),
    ("qualification", "qualification.qualification", "qualification_only_latest_changes"),
    ("control_objectives", "control_objectives.mapping_archive", "mapping_archive_is_append_only"),
    ("report_composer", "report_composer.layout_revision", "layout_revision_is_append_only"),
]

#: (module, constraint) of each reference to a card version (project.system).
VERSION_REFERENCES = [
    ("qualification", "qualification_system_id_fkey"),
    ("controls", "submission_answer_system_version_pid_fkey"),
    ("control_objectives", "fk_project_system_id_project_system"),
    ("report_composer", "generated_report_system_id_fkey"),
    ("report_composer", "generated_report_compare_to_fkey"),
]


@pytest.fixture(scope="module")
def bed():
    b = ob.build("module-owners")
    yield b
    b.stop()


def _a_table(bed, schema):
    return bed.scalar(DB, f"SELECT tablename FROM pg_tables WHERE schemaname = '{schema}'"
                          " AND tablename NOT LIKE '\\_%' AND tablename NOT IN ('alembic_version', 'schema_migration')"
                          " ORDER BY 1 LIMIT 1")


@pytest.mark.parametrize("module", MODULES)
def test_module_tables_belong_to_the_module_owner(bed, module):
    bed.require(module)
    owners = {r["tableowner"] for r in bed.rows(DB, f"SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = '{module}'")}
    assert owners == {f"{module}_owner"}


@pytest.mark.parametrize("module", MODULES)
def test_module_sequences_belong_to_the_module_owner(bed, module):
    bed.require(module)
    owners = {r["sequenceowner"] for r in bed.rows(DB, f"SELECT DISTINCT sequenceowner FROM pg_sequences"
                                                       f" WHERE schemaname = '{module}'")}
    assert owners <= {f"{module}_owner"}, owners


@pytest.mark.parametrize("module", MODULES)
def test_the_runtime_role_cannot_create_in_its_schema(bed, module):
    bed.require(module)
    assert bed.scalar(DB, f"SELECT has_schema_privilege('{module}_rw', '{module}', 'CREATE')") == "f"


@pytest.mark.parametrize("module", MODULES)
def test_the_runtime_role_holds_no_trigger_or_truncate(bed, module):
    bed.require(module)
    held = [r["rel"] for r in bed.rows(DB, f"""
        SELECT c.oid::regclass::text AS rel FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = '{module}' AND c.relkind IN ('r', 'p')
           AND (has_table_privilege('{module}_rw', c.oid, 'TRIGGER') OR has_table_privilege('{module}_rw', c.oid, 'TRUNCATE'))
         ORDER BY 1""")]
    assert held == []


@pytest.mark.parametrize("module", MODULES)
def test_the_runtime_role_cannot_alter_its_tables(bed, module):
    bed.require(module)
    table = _a_table(bed, module)
    _, err = ob.as_role(bed, DB, f"{module}_rw",
                        f"BEGIN; ALTER TABLE {module}.\"{table}\" ADD COLUMN owner_probe int; ROLLBACK;")
    assert "must be owner" in err, f"{module}_rw altered {module}.{table}: {err[-200:]}"


@pytest.mark.parametrize("module,table", [(m, t) for m, ts in APPEND_ONLY.items() for t in ts])
def test_the_runtime_role_only_inserts_and_reads_append_only_tables(bed, module, table):
    bed.require(module)
    granted = {p: bed.scalar(DB, f"SELECT has_table_privilege('{module}_rw', '{module}.{table}', '{p}')")
               for p in ("INSERT", "SELECT", "UPDATE", "DELETE")}
    assert granted == {"INSERT": "t", "SELECT": "t", "UPDATE": "f", "DELETE": "f"}


@pytest.mark.parametrize("module,table,trigger", GUARDS)
def test_the_runtime_role_cannot_lift_a_module_guard(bed, module, table, trigger):
    bed.require(module)
    _, err = ob.as_role(bed, DB, f"{module}_rw", f"BEGIN; ALTER TABLE {table} DISABLE TRIGGER {trigger}; ROLLBACK;")
    assert "must be owner" in err, f"{module}_rw disabled {trigger}: {err[-200:]}"


@pytest.mark.parametrize("module,table,trigger", GUARDS)
def test_a_migration_cannot_lift_a_module_guard(bed, module, table, trigger):
    """The migrator acts as the owner; the guard alarm still keeps the trigger on."""
    bed.require(module)
    _, err = ob.as_role(bed, DB, f"{module}_migrator", f"BEGIN; ALTER TABLE {table} DISABLE TRIGGER {trigger}; ROLLBACK;")
    assert "cannot be disabled or dropped" in err, f"{module}_migrator on {trigger}: {err[-200:]}"


@pytest.mark.parametrize("module,constraint", VERSION_REFERENCES)
def test_a_card_version_reference_restricts(bed, module, constraint):
    bed.require(module)
    kind = bed.scalar(DB, f"SELECT confdeltype FROM pg_constraint WHERE conname = '{constraint}'"
                          f" AND connamespace = '{module}'::regnamespace")
    assert kind == "r", f"{constraint}: confdeltype {kind!r}"


def test_a_qualification_cannot_be_deleted(bed):
    bed.require("qualification")
    _, err = ob.as_su(bed, DB, """
        BEGIN;
        INSERT INTO project.system (number, name) VALUES (900, 'kept probe');
        INSERT INTO qualification.qualification (id, "systemName", "systemVersion", company, description,
               "targetUseCase", "targetUsers", updated_at, system_id)
          SELECT 'kept-probe', 'probe', '1', 'c', 'd', 'u', 'p', now(), pid FROM project.system WHERE number = 900;
        DELETE FROM qualification.qualification WHERE id = 'kept-probe';
        ROLLBACK;""")
    assert "is kept" in err, f"the delete went through: {err[-300:]}"


def test_qualifications_cannot_be_truncated(bed):
    bed.require("qualification")
    _, err = ob.as_su(bed, DB, "BEGIN; TRUNCATE qualification.qualification CASCADE; ROLLBACK;")
    assert "is kept" in err, f"the truncate went through: {err[-300:]}"


def test_the_platform_reads_which_card_version_a_qualification_is_on(bed):
    bed.require("qualification")
    assert bed.scalar(DB, "SELECT has_column_privilege('platform_rw', 'qualification.qualification', 'system_id',"
                          " 'SELECT')") == "t"


@pytest.mark.parametrize("module,expected", [("qualification", "t"), ("controls", "f"),
                                             ("control_objectives", "f"), ("report_composer", "f")])
def test_qualification_may_make_temporary_tables_and_no_other_module_may(bed, module, expected):
    bed.require(module)
    assert bed.scalar(DB, f"SELECT has_database_privilege('{module}_rw', current_database(), 'TEMP')") == expected


# a module migration on a schema without its owner


C = "c0000000-0000-4000-8000-00000000000c"


@pytest.fixture(scope="module")
def unowned():
    """A project database whose module schemas are left with platform_rw, as on a stack where
    postgres-setup has not made the owner roles: the module migrations must refuse to run there."""
    b = ob.build("unowned", modules=False, projects=(C,))
    for module in MODULES:
        ob.as_su(b, ib.project_db(C), f"ALTER SCHEMA {module} OWNER TO platform_rw")
    ib.migrate_modules(b)
    yield b
    b.stop()


@pytest.mark.parametrize("module", MODULES)
def test_a_module_migration_refuses_a_schema_without_its_owner(unowned, module):
    problem = unowned.problems.get(module, "")
    assert "postgres-setup" in problem, f"{module} migrated a schema without its owner: {problem or 'no refusal'}"
    owners = {r["tableowner"] for r in unowned.rows(ib.project_db(C),
                                                    f"SELECT DISTINCT tableowner FROM pg_tables WHERE schemaname = '{module}'")}
    assert "platform_rw" not in owners and f"{module}_rw" not in owners, owners
