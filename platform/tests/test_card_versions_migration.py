"""Migration 0003: core.system becomes the saved versions of a project's AI card.

WP2 of pipeline-2026-09-23 (03-specs.md). Each test makes its own scratch
database (tests/core_scratch.py), so the state before the migration is known.
"""
import psycopg
import pytest

# These tests pin core.system's history (migrations 0003-0005) on old layouts that skip postgres-setup,
# so they migrate up to 0005: the ledger's 0006 needs the schema postgres-setup makes, and in production
# the platform waits for postgres-setup (service_completed_successfully) before it migrates.
from tests.core_scratch import (
    apply_platform_migrations,
    give_core_system_to_platform,
    needs_superuser,
    project_databases_platform_part,
    scratch_database,
)

pytestmark = needs_superuser

M0003 = "0003_card_versions_in_core_system.sql"
MCAS = "1e722ea2-4ce3-47fa-81bf-11a6b53ad679"
GUARD = "core.system must be owned by platform_rw: run init/project-databases.sql as the superuser"


def _one(dsn, query, params=()):
    with psycopg.connect(dsn) as conn:
        return conn.execute(query, params).fetchone()


def _columns(dsn):
    with psycopg.connect(dsn) as conn:
        rows = conn.execute(
            "select column_name, is_nullable from information_schema.columns"
            " where table_schema = 'core' and table_name = 'system'"
        ).fetchall()
    return {name: nullable for name, nullable in rows}


def _applied(dsn):
    with psycopg.connect(dsn) as conn:
        return {r[0] for r in conn.execute("select name from core.schema_migration").fetchall()}


# ── D1 / A2: the superuser hands core.system to the platform ────────────────


def test_d1_project_databases_sql_gives_core_system_to_platform_rw():
    """D1: one idempotent line in init/project-databases.sql, in the platform database."""
    assert "ALTER TABLE core.system OWNER TO platform_rw" in project_databases_platform_part()


def test_d1_running_the_platform_part_twice_makes_platform_rw_the_owner():
    with scratch_database(old_layout=True) as (su, _rw):
        for _ in range(2):  # it runs on every start of postgres-setup
            with psycopg.connect(su, autocommit=True) as conn:
                conn.execute(project_databases_platform_part())
        owner = _one(su, "select pg_get_userbyid(relowner) from pg_class where oid = 'core.system'::regclass")
        assert owner == ("platform_rw",)


# ── S2.6 fresh database ─────────────────────────────────────────────────────


def test_s2_6_on_a_fresh_database_0003_succeeds_and_core_system_is_empty():
    with scratch_database(old_layout=True) as (su, rw):
        give_core_system_to_platform(su)
        apply_platform_migrations(rw, upto="0005")
        assert M0003 in _applied(rw)
        assert _one(rw, "select count(*) from core.system") == (0,)
        columns = _columns(rw)
        assert columns.get("number") == "NO"
        assert "created_by" in columns
        assert _one(rw, "select to_regclass('core.ai_system'), to_regclass('core.ai_system_version')") == (None, None)


def test_s2_6_constraints_after_0003():
    """Step 5: (project_id, number) is the key; (project_id, name, version) is not."""
    with scratch_database(old_layout=True) as (su, rw):
        give_core_system_to_platform(su)
        apply_platform_migrations(rw, upto="0005")
        with psycopg.connect(rw) as conn:
            constraints = {r[0] for r in conn.execute(
                "select conname from pg_constraint where conrelid = 'core.system'::regclass").fetchall()}
            indexes = {r[0] for r in conn.execute(
                "select indexname from pg_indexes where schemaname = 'core' and tablename = 'system'").fetchall()}
            comment = conn.execute("select obj_description('core.system'::regclass)").fetchone()[0]
        assert "system_project_number_key" in constraints
        assert "system_project_id_name_version_key" not in constraints
        assert "system_identity_idx" not in indexes
        assert "system_project_idx" in indexes
        assert comment == "One saved AI card version of the project's one AI system; number 1, 2, ... per project."


def test_s2_6_number_must_be_positive():
    with scratch_database(old_layout=True) as (su, rw):
        give_core_system_to_platform(su)
        apply_platform_migrations(rw, upto="0005")
        with psycopg.connect(rw) as conn:
            pid = conn.execute("insert into core.project (name, slug) values ('p', 'p') returning pid").fetchone()[0]
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute("insert into core.system (project_id, name, number) values (%s, 'x', 0)", (pid,))


def test_s2_6_grants_on_core_system_are_kept():
    with scratch_database(old_layout=True) as (su, rw):
        give_core_system_to_platform(su)
        apply_platform_migrations(rw, upto="0005")
        assert M0003 in _applied(rw)
        with psycopg.connect(su) as conn:
            for role in ("qualification_rw", "control_objectives_rw", "controls_rw", "engine_rw", "dashboard_ro"):
                assert conn.execute("select has_table_privilege(%s, 'core.system', 'SELECT')", (role,)).fetchone()[0], role
            for role in ("qualification_rw", "control_objectives_rw", "engine_rw", "catalogue_rw"):
                assert conn.execute("select has_table_privilege(%s, 'core.system', 'REFERENCES')", (role,)).fetchone()[0], role


# ── S2.7 the live shape ─────────────────────────────────────────────────────


def _live_shaped(su, rw):
    """0001, a project with MCAS in core.system (as qualification made it),
    a second project that never named a system, then 0002."""
    apply_platform_migrations(rw, upto="0001")
    with psycopg.connect(rw) as conn:
        mcas_project = conn.execute(
            "insert into core.project (name, slug) values ('MCAS project', 'mcas') returning pid").fetchone()[0]
        empty_project = conn.execute(
            "insert into core.project (name, slug) values ('Empty', 'empty') returning pid").fetchone()[0]
        conn.execute(
            "insert into core.system (pid, project_id, name, version, provider, description)"
            " values (%s, %s, 'MCAS', 'v1.2.0', 'LIST', 'microcredit scoring')",
            (MCAS, mcas_project),
        )
    apply_platform_migrations(rw, upto="0002")
    return mcas_project, empty_project


def test_s2_7_on_the_live_shape_every_pid_is_kept_and_mcas_is_number_1():
    with scratch_database(old_layout=True) as (su, rw):
        mcas_project, empty_project = _live_shaped(su, rw)
        with psycopg.connect(rw) as conn:
            version_pids = {str(r[0]) for r in conn.execute("select pid from core.ai_system_version").fetchall()}
        give_core_system_to_platform(su)
        apply_platform_migrations(rw, upto="0005")
        assert M0003 in _applied(rw)
        with psycopg.connect(rw) as conn:
            rows = conn.execute("select pid, project_id, number, name, version from core.system").fetchall()
        by_pid = {str(r[0]): r for r in rows}
        assert version_pids <= set(by_pid), "every version pid of 0002 is a core.system row"
        mcas = by_pid[MCAS]
        assert (mcas[1], mcas[2], mcas[3], mcas[4]) == (mcas_project, 1, "MCAS", "v1.2.0")
        # the draft 0002 made for the project that never named a system is carried too
        empty_rows = [r for r in rows if r[1] == empty_project]
        assert [r[2] for r in empty_rows] == [1]
        assert _one(rw, "select to_regclass('core.ai_system'), to_regclass('core.ai_system_version')") == (None, None)
        assert _one(rw, "select count(*) from pg_proc where proname = 'ai_system_version_is_frozen'") == (0,)


# ── S2.8 the ownership guard ────────────────────────────────────────────────


def test_s2_8_without_ownership_0003_fails_with_the_guard_message_and_is_not_recorded():
    with scratch_database(old_layout=True) as (su, rw):
        apply_platform_migrations(rw, upto="0002")
        with pytest.raises(psycopg.errors.RaiseException, match=GUARD):
            apply_platform_migrations(rw, upto="0005")
        assert M0003 not in _applied(rw)
        assert "0002_one_ai_system_per_project.sql" in _applied(rw)
        # and it succeeds once the superuser line has run
        give_core_system_to_platform(su)
        apply_platform_migrations(rw, upto="0005")
        assert M0003 in _applied(rw)


# ── S2.4 only the latest version changes (the trigger itself) ───────────────


def test_s2_4_the_trigger_refuses_changes_to_an_older_version_and_to_number_or_project():
    with scratch_database(old_layout=True) as (su, rw):
        give_core_system_to_platform(su)
        apply_platform_migrations(rw, upto="0005")
        with psycopg.connect(rw, autocommit=True) as conn:
            project = conn.execute("insert into core.project (name, slug) values ('p', 'p') returning pid").fetchone()[0]
            other = conn.execute("insert into core.project (name, slug) values ('q', 'q') returning pid").fetchone()[0]
            v1 = conn.execute("insert into core.system (project_id, name, number) values (%s, 'S', 1) returning pid",
                              (project,)).fetchone()[0]
            v2 = conn.execute("insert into core.system (project_id, name, number) values (%s, 'S', 2) returning pid",
                              (project,)).fetchone()[0]
            with pytest.raises(psycopg.errors.RaiseException, match="is not the latest and cannot change"):
                conn.execute("update core.system set description = 'late' where pid = %s", (v1,))
            conn.execute("update core.system set description = 'fine' where pid = %s", (v2,))
            with pytest.raises(psycopg.errors.RaiseException):
                conn.execute("update core.system set number = 3 where pid = %s", (v2,))
            with pytest.raises(psycopg.errors.RaiseException):
                conn.execute("update core.system set project_id = %s where pid = %s", (other, v2))
