"""The every-start init file cannot undo the retirement of core.system.

The cutover retires core.system (owner to the superuser, every privilege revoked, a comment
beginning with `retired:`) and a later step drops it. postgres-setup runs
init/project-databases.sql as the superuser on every start, and an older version of that file
gave core.system back to platform_rw. These tests build the pre-isolation layout, retire it the
way the cutover does, run the file again and check that nothing came back; then drop it and run
the file again. They are the non-vacuous form of the guard tests in test_project_system.py.

Needs PLATFORM_TEST_SUPERUSER_URL (a throwaway superuser DSN, never the live database).
"""
from __future__ import annotations

import psycopg
import pytest

from tests.core_scratch import (
    apply_platform_migrations,
    needs_superuser,
    project_databases_platform_part,
    scratch_database,
)

ROLES = ["platform_rw", "qualification_rw", "control_objectives_rw", "controls_rw", "engine_rw",
         "catalogue_rw", "dashboard_ro", "report_ro", "report_composer_rw"]
PRIVILEGES = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"]
RETIRED_SCHEMAS = ["qualification", "control_objectives", "engine"]
RETIRED = "retired: isolation cutover C9 (test); dropped in stage 7"


def _setup_part(su: str) -> None:
    with psycopg.connect(su, autocommit=True) as conn:
        conn.execute(project_databases_platform_part())


def _existing_roles(conn) -> list[str]:
    return [r for r in ROLES if conn.execute("select 1 from pg_roles where rolname = %s", (r,)).fetchone()]


def _retire(su: str) -> None:
    """What the cutover does to core.system and the shared module schemas."""
    with psycopg.connect(su, autocommit=True) as conn:
        roles = _existing_roles(conn)
        conn.execute("ALTER TABLE core.system OWNER TO CURRENT_USER")
        conn.execute(f"REVOKE ALL ON core.system FROM PUBLIC, {', '.join(roles)}")
        conn.execute(f"COMMENT ON TABLE core.system IS '{RETIRED}'")
        for schema in RETIRED_SCHEMAS:
            conn.execute(f"ALTER SCHEMA {schema} OWNER TO CURRENT_USER")
            conn.execute(f"REVOKE ALL ON SCHEMA {schema} FROM PUBLIC, {', '.join(roles)}")
            conn.execute(f"COMMENT ON SCHEMA {schema} IS '{RETIRED}'")


def _state(su: str) -> dict:
    with psycopg.connect(su) as conn:
        owner, acl, comment = conn.execute(
            "select pg_get_userbyid(relowner), relacl::text, obj_description(oid, 'pg_class')"
            " from pg_class where oid = 'core.system'::regclass").fetchone()
        privileges = {(role, p) for role in _existing_roles(conn) for p in PRIVILEGES
                      if conn.execute("select has_table_privilege(%s, 'core.system', %s)", (role, p)).fetchone()[0]}
        schemas = {s: conn.execute("select pg_get_userbyid(nspowner), nspacl::text from pg_namespace"
                                   " where nspname = %s", (s,)).fetchone() for s in RETIRED_SCHEMAS}
        constraints = {r[0] for r in conn.execute(
            "select conname from pg_constraint where conrelid = 'core.system'::regclass").fetchall()}
        superuser = conn.execute("select current_user").fetchone()[0]
    return {"owner": owner, "acl": acl, "comment": comment, "privileges": privileges, "schemas": schemas,
            "constraints": constraints, "superuser": superuser}


@needs_superuser
def test_a_retired_core_system_stays_retired_when_postgres_setup_runs_again():
    with scratch_database(old_layout=True) as (su, rw):
        # the pre-isolation stack: setup, platform migrations, setup at the next start
        _setup_part(su)
        apply_platform_migrations(rw)
        _setup_part(su)
        assert _state(su)["owner"] == "platform_rw", "precondition: the old layout hands core.system over"
        _retire(su)
        before = _state(su)
        assert before["owner"] == before["superuser"] and before["privileges"] == set()
        _setup_part(su)  # the next start of postgres-setup
        after = _state(su)
    assert after["owner"] == after["superuser"], \
        f"P1-D3: init/project-databases.sql gave the retired core.system to {after['owner']}"
    assert after["privileges"] == set(), f"P1-D3: a role regained {sorted(after['privileges'])} on core.system"
    assert after["acl"] == before["acl"] and after["comment"] == before["comment"]
    assert after["schemas"] == before["schemas"], "G4: the setup touched a retired module schema"
    assert after["constraints"] == before["constraints"], "P1-D3: the setup changed the retired table's keys"


@needs_superuser
def test_the_setup_and_the_platform_migrations_run_after_the_stage_7_drop():
    with scratch_database(old_layout=True) as (su, rw):
        _setup_part(su)
        apply_platform_migrations(rw)
        _retire(su)
        with psycopg.connect(su, autocommit=True) as conn:
            conn.execute("DROP SCHEMA qualification, control_objectives, engine CASCADE")
            conn.execute("DROP TABLE core.system CASCADE")
            conn.execute("DROP FUNCTION IF EXISTS core.system_only_latest_changes()")
        try:
            _setup_part(su)
        except psycopg.Error as exc:
            pytest.fail(f"I2.8: init/project-databases.sql fails after the stage-7 drop: {type(exc).__name__}")
        assert apply_platform_migrations(rw) == [], "every platform migration was already recorded"
        with psycopg.connect(su) as conn:
            core = {r[0] for r in conn.execute(
                "select relname from pg_class c join pg_namespace n on n.oid = c.relnamespace"
                " where n.nspname = 'core' and c.relkind in ('r', 'p')").fetchall()}
    # core.outbox is the platform's own ledger outbox (migration 0008), not a module's table
    assert core == {"project", "project_member", "schema_migration", "outbox"}, f"I1.3: core has {sorted(core)}"


@needs_superuser
def test_a_platform_that_never_had_core_system_migrates_without_it():
    """On a fresh volume (the new init/platform-db.sql) platform migrations 0002..0005
    run and make no core.system; the setup that follows does not either."""
    with scratch_database() as (su, rw):
        _setup_part(su)
        ran = apply_platform_migrations(rw)
        _setup_part(su)
        with psycopg.connect(su) as conn:
            system = conn.execute("select to_regclass('core.system')").fetchone()[0]
            freeze = conn.execute("select to_regclass('core.ai_system'), to_regclass('core.ai_system_version')"
                                  ).fetchone()
            composer_reads = conn.execute(
                "select has_table_privilege('report_composer_rw', 'core.project_member', 'SELECT')"
                " from pg_roles where rolname = 'report_composer_rw'").fetchone()
    assert "0003_card_versions_in_core_system.sql" in ran and "0005_the_composer_reads_members.sql" in ran
    assert system is None, "P1-D2: a migration made core.system on a fresh volume"
    assert freeze == (None, None), "0003 step 6 still drops the freeze model of 0002"
    assert composer_reads in (None, (True,)), "I1.4: 0005 lets report_composer_rw read core.project_member"
