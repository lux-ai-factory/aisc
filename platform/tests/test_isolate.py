"""The live data move: python -m platform_service.isolate (01-specs.md section 12, D5, D13..D15).

Isolation 2026-09-25, stage 2: written before the tool. Every test below except the three
`test_fixture_*` ones fails with ModuleNotFoundError (platform_service.isolate) until stage 4
writes it; the fixture tests pass now and prove the synthetic source they run on is what it says.

The world each test runs on is built by tests/isolate_support.py (read its docstring): a throwaway
source database shaped like the live `platform` at its old-layout heads, two projects A < B with
rows in every moving schema, and their project databases at the new heads.

Needs PLATFORM_TEST_SUPERUSER_URL (throwaway superuser, never port 5432) and
PLATFORM_TEST_DATABASE_URL (platform_rw on the same cluster); skips without them.

Interface pinned by these tests (stage 3/4 implement exactly this)
------------------------------------------------------------------
CLI: ``python -m platform_service.isolate <subcommand> (--project PID [--project PID ...] | --all)
[--dry-run] [--report PATH]``, run from ``platform/``.

- Subcommands: ``plan``, ``provision``, ``copy`` (``--dry-run`` allowed), ``verify``,
  ``verify-dump <dump file> [...]``, ``report``.
- Connection: env ``ISOLATE_SUPERUSER_URL``, a superuser DSN whose database is the source
  (``platform`` live, a throwaway here). Target databases are ``project_<hex>`` on the same server
  (projectdb.database_name). ``form_library.*`` and ``report_library.*`` are in the source database.
- Exit code 0 on success; non-zero on any refusal, conflict, mismatch or failure (I12.16).
- stdout: the human summary; stderr: logs. Neither ever contains a row value or a credential.
- ``verify-dump`` restores the dump files with ``pg_restore`` found on PATH (``--no-owner``) into a
  database it creates and drops, reads the moving tables from it and core.project from
  ISOLATE_SUPERUSER_URL's database, and then verifies exactly as ``verify`` does.
- Reads of a target that change nothing end in ROLLBACK, so ``plan``, ``copy --dry-run`` and an
  ``already done`` project leave the rows written in every target (pg_stat_database tup_inserted/updated/deleted) unchanged.

Report JSON (``--report``; keys and counts only, never row values, I12.15)::

    {
      "subcommand": "copy", "dry_run": false, "snapshot_time": "<ISO 8601>",
      "classification": {"<schema.table>": "root" | "owned" | "needed" | "library"
                         | "bookkeeping" | "stays shared" | "unclassified"},
      "refusals": [{"reason": "<named reason>", "table": "<schema.table>" | null,
                    "project": "<pid>" | null, "projects": ["<pid>", ...], "keys": [{...}, ...]}],
      "projects": {"<pid>": {
          "database": "project_<hex>",
          "status": "planned" | "copied" | "already done" | "failed" | "verified" | "missing database",
          "tables": {"<source schema.table>": {
              "target": "<schema.table>", "source_rows": int, "to_copy": int,
              "already_present": int, "copied": int, "count": int,   # to_copy = size of the
              # project's copied set; already_present = those of it already in the target (equal);
              # copied = inserted by this run; count = target rows with the copied set's keys
              "source_md5": "<32 hex>", "target_md5": "<32 hex>"}},
          "sequences": {"<schema.sequence>": {"last_value": int, "is_called": bool}}}},
      "library": {"status": "...", "tables": {<as above>}},
      "unowned": [{"table": "<schema.table>", "key": {"<pk column>": <pk value>}, "reason": "..."}],
      "coverage": {"<schema.table>": {"source_rows": int, "covered": int, "missing": int}}
    }

``source_md5``/``target_md5`` are md5(string_agg(ROW(<shared columns in target column order>)::text,
E'\\n' ORDER BY row_text)) under TimeZone=UTC, DateStyle=ISO, extra_float_digits=3, bytea_output=hex,
over the copied set of that project (I12.10). ``coverage`` is written by ``verify`` (I12.13).

Named refusal reasons: ``unclassified table``, ``owned by two projects``, ``cross-project reference``,
``unknown project``, ``missing database``, ``source not at old head``, ``target not at new head``,
``missing template``, ``active sessions``, ``column coverage``, ``target not empty and not equal``,
``count mismatch``, ``checksum mismatch``.

Decisions taken here (recorded in 02-tests.md):
- report_composer.preset (composer 0005, platform-wide by D4) is a library table: every row goes to
  ``report_library.preset`` in platform, none into a project (its FK to core.project would otherwise
  make it a root table; the spec's I12.1/I12.2 do not name it).
- With the forms tables absent (the old head before the forms migrations), the old-head check
  accepts the pre-forms qualification history and the library copy is skipped.
- ``copy`` refuses (``missing database``) when a project in core.project has no database; ``plan``
  reports that project with status ``missing database``.
- A project database made by ``isolate provision`` belongs to platform_rw, as one made by POST /projects.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

from tests import isolate_support as S

pytestmark = pytest.mark.skipif(
    not (S.SUPERUSER_DSN and S.PLATFORM_RW_DSN),
    reason="PLATFORM_TEST_SUPERUSER_URL and PLATFORM_TEST_DATABASE_URL (throwaway) are needed",
)


@pytest.fixture
def make_world():
    made = []

    def make(forms: bool = True):
        w = S.build_world(forms)
        made.append(w)
        return w

    yield make
    for w in made:
        S.drop_world(w)


@pytest.fixture
def rpt(tmp_path):
    counter = iter(range(1000))
    return lambda name="r": tmp_path / f"{name}-{next(counter)}.json"


def copied(w, res):
    assert res.returncode == 0, res.output[-3000:]
    for pid in w.pids:
        assert res.status(pid) in {"copied", "already done"}, res.report


def target_keys(w, pid, table):
    with w.target(pid) as c:
        return S.keys(c, table, S.primary_key(c, table))


def moving_tables(conn) -> list[str]:
    return [t for t in S.user_tables(conn)
            if t.split(".")[0] in S.MOVING_SCHEMAS or t == "core.system"]


# ── the fixture itself (these pass now) ──────────────────────────────────────


def test_fixture_source_is_the_live_shape_with_the_synthetic_rows(make_world):
    w = make_world()
    with w.source() as c:
        tables = set(S.user_tables(c))
        for t in ["core.system", "qualification.form_version_question", "engine.aisc_backend_derived",
                  "report_composer.preset", "form_library.form", "report_library.preset"]:
            assert t in tables, t
        count = lambda t: c.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.SQL(t))).fetchone()[0]
        assert count("core.project") == 2
        assert count("core.system") == 3
        assert count("qualification.form") == 3 and count("form_library.form") == 1
        assert count("engine.aisc_backend_metric") == 4
        assert count("engine.aisc_backend_project") == 3
        assert c.execute("SELECT last_value, is_called FROM control_objectives.risk_id_seq").fetchone() == (10, True)
        assert S.fk_orphans(c) == []


def test_fixture_targets_hold_only_the_seed_and_the_new_heads(make_world):
    w = make_world()
    for pid in w.pids:
        with w.target(pid) as c:
            assert S.columns(c, "project.system")[:2] == ["pid", "number"]
            assert "project_id" not in S.columns(c, "qualification.qualification")
            assert "project_id" in S.columns(c, "engine.aisc_backend_project")  # I7.9: engine keeps it
            assert c.execute("SELECT count(*) FROM qualification.form").fetchone()[0] == 1
            assert c.execute("SELECT count(*) FROM qualification.qualification_answer").fetchone()[0] == 0
            names = {r[0] for r in c.execute("SELECT name FROM provision.template_migration")}
            assert set(S.NEW_TEMPLATE) <= names
            assert S.fk_orphans(c) == []


def test_fixture_forms_absent_world_builds(make_world):
    w = make_world(forms=False)
    with w.source() as c:
        assert "qualification.form" not in S.user_tables(c)
        assert "form_version_id" not in S.columns(c, "qualification.qualification")
        assert S.fk_orphans(c) == []


# ── I12.1..I12.3 classification and placement ────────────────────────────────


def test_I12_1_plan_classifies_every_table_of_the_live_shape_from_the_catalog(make_world, rpt):
    S.require_tool()
    w = make_world()
    r = rpt("plan")
    res = S.run(w, "plan", "--all", report=r)
    assert res.returncode == 0, res.output[-3000:]
    cls = res.report["classification"]
    with w.source() as c:
        for t in moving_tables(c):
            assert t in cls, f"I12.1: {t} not classified"
            assert cls[t] != "unclassified", t
    for t in S.BOOKKEEPING:
        assert cls[t] == "bookkeeping", t
    for t in ("qualification.qualification", "control_objectives.project", "engine.aisc_backend_project",
              "report_composer.layout", "report_composer.template", "core.system"):
        assert cls[t] == "root", t
    assert cls["qualification.form_version_question"] in {"needed", "library"}
    assert cls["report_composer.preset"] == "library"


def test_I12_1_an_unclassified_table_refuses_the_copy(make_world, rpt):
    S.require_tool()
    w = make_world()
    with w.source() as c:
        c.execute("CREATE TABLE qualification.stray (id int PRIMARY KEY, note text)")
        c.execute("INSERT INTO qualification.stray VALUES (1, 'x')")
    before = {p: S.digests(w.target_dsn(p)) for p in w.pids}
    res = S.run(w, "copy", "--all", report=rpt())
    S.assert_refused(res, "unclassified table", table="qualification.stray")
    assert {p: S.digests(w.target_dsn(p)) for p in w.pids} == before


def test_I12_3_a_table_added_later_is_placed_by_its_foreign_keys_without_code(make_world, rpt):
    S.require_tool()
    w = make_world()
    ddl = ("CREATE TABLE engine.extra (id bigint PRIMARY KEY,"
           " ai_system_id bigint NOT NULL REFERENCES engine.aisc_backend_aisystem(id), note text)")
    with w.source() as c:
        c.execute(ddl)
        c.execute("INSERT INTO engine.extra VALUES (10, 1, 'a'), (20, 2, 'b')")
    for p in w.pids:
        with w.target(p) as c:
            c.execute(ddl)
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    assert target_keys(w, w.A, "engine.extra") == {10}
    assert target_keys(w, w.B, "engine.extra") == {20}


def test_I12_2_I12_3_every_row_lands_in_its_own_project_database(make_world, rpt):
    S.require_tool()
    w = make_world()
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    for pid, tables in S.expected_placement(w).items():
        for table, want in tables.items():
            got = target_keys(w, pid, table)
            assert {str(k) for k in got} == {str(k) for k in want}, f"{pid[:8]} {table}"
    with w.target(w.A) as c:
        assert c.execute("SELECT pid::text, number FROM project.system ORDER BY number").fetchall() == [
            (w.ids["sA1"], 1), (w.ids["sA2"], 2)]
        assert c.execute("SELECT count(*) FROM report_composer.layout_block").fetchone()[0] == 2
    with w.target(w.B) as c:
        assert c.execute("SELECT count(*) FROM report_composer.layout_block").fetchone()[0] == 0


def test_I12_3_D14_self_references_identifying_children_and_historical_rows(make_world, rpt):
    """cq1 copies dq1 (self-reference): B needs dq1 and its owner form; ai_component 2's dataset
    is component 1; derived 3 is an identifying child of metric 3 and needs its base metric 2;
    ansA0 answers a card version that is no longer the latest, which its trigger would refuse."""
    S.require_tool()
    w = make_world()
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    with w.target(w.B) as c:
        assert c.execute("SELECT copied_from_id FROM qualification.form_question WHERE id='cq1'").fetchone() == ("dq1",)
        assert c.execute("SELECT count(*) FROM qualification.form_version_question"
                         " WHERE form_version_id='custom-v1'").fetchone()[0] == 2
    with w.target(w.A) as c:
        assert c.execute("SELECT source_dataset_id FROM engine.aisc_backend_aicomponent WHERE id=2").fetchone() == (1,)
        assert c.execute("SELECT base_metric_id FROM engine.aisc_backend_derived WHERE metric_ptr_id=3").fetchone() == (2,)
        assert c.execute("SELECT answer FROM qualification.qualification_answer WHERE id='ansA0'").fetchone() == ("old",)
        assert S.fk_orphans(c) == []


# ── I12.4 conflicts abort before any write ───────────────────────────────────


def _no_write_anywhere(w, before):
    assert {p: S.digests(w.target_dsn(p)) for p in w.pids} == before["targets"]
    assert S.digests(w.source_dsn, ("form_library", "report_library")) == before["library"]


def _snapshot(w):
    return {"targets": {p: S.digests(w.target_dsn(p)) for p in w.pids},
            "library": S.digests(w.source_dsn, ("form_library", "report_library"))}


def test_I12_4_a_row_owned_by_two_projects_aborts_before_any_write(make_world, rpt):
    S.require_tool()
    w = make_world()
    with w.source() as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        # evaluation_plugin 1 is A's, component 3 is B's
        c.execute("INSERT INTO engine.aisc_backend_evaluationinput (id, pid, name, description, created_at, value,"
                  " component_id, evaluation_plugin_id) VALUES (2, gen_random_uuid(), 'i2', '', now(), '{}', 3, 1)")
    before = _snapshot(w)
    res = S.run(w, "copy", "--all", report=rpt())
    S.assert_refused(res, {"owned by two projects", "cross-project reference"},
                     table="engine.aisc_backend_evaluationinput", projects=(w.A, w.B))
    _no_write_anywhere(w, before)


def test_I12_4_a_cross_project_stamp_aborts_before_any_write(make_world, rpt):
    S.require_tool()
    w = make_world()
    with w.source() as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        c.execute("UPDATE engine.aisc_backend_evaluation SET system_id = %s WHERE id = 1", (w.ids["sB1"],))
    before = _snapshot(w)
    res = S.run(w, "copy", "--all", report=rpt())
    S.assert_refused(res, {"cross-project reference", "owned by two projects"},
                     table="engine.aisc_backend_evaluation", projects=(w.A, w.B))
    _no_write_anywhere(w, before)


def test_I12_4_a_root_row_of_a_project_not_in_core_project_aborts(make_world, rpt):
    S.require_tool()
    w = make_world()
    ghost = str(uuid.uuid4())
    with w.source() as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        c.execute("INSERT INTO report_composer.template (project_id, name, font, font_size_pt, primary_color,"
                  " accent_color, created_by, updated_by) VALUES (%s, 'g', 'inter', 10, '#000000', '#000000',"
                  " 'x', 'x')", (ghost,))
    before = _snapshot(w)
    res = S.run(w, "copy", "--all", report=rpt())
    S.assert_refused(res, "unknown project", table="report_composer.template")
    _no_write_anywhere(w, before)


# ── I12.5 unowned rows ───────────────────────────────────────────────────────


def test_I12_5_unowned_rows_are_reported_by_key_and_reason_and_not_moved(make_world, rpt):
    S.require_tool()
    w = make_world()
    res = S.run(w, "copy", "--all", report=rpt())
    copied(w, res)
    got = {(u["table"], next(iter(u["key"].values()))) for u in res.report["unowned"]}
    assert got == S.UNOWNED, got
    assert all(u.get("reason") for u in res.report["unowned"])
    # the unused form is not unowned: it is in the library target (I12.5)
    assert not any(u["table"].startswith("qualification.form") for u in res.report["unowned"])
    for pid in w.pids:
        assert 3 not in target_keys(w, pid, "engine.aisc_backend_project")
        assert 4 not in target_keys(w, pid, "engine.aisc_backend_metric")


def test_I12_5_I12_6_a_project_without_a_database_is_reported_and_refuses_copy(make_world, rpt):
    S.require_tool()
    w = make_world()
    c_pid = "ffffffff-ffff-4fff-bfff-" + uuid.uuid4().hex[:12]
    with w.source() as c:
        c.execute("INSERT INTO core.project (pid, name, slug) VALUES (%s, 'Gamma', %s)", (c_pid, f"iso-c-{w.tag}"))
    plan = S.run(w, "plan", "--all", report=rpt())
    assert plan.status(c_pid) == "missing database", plan.report
    before = _snapshot(w)
    S.assert_refused(S.run(w, "copy", "--all", report=rpt()), "missing database", projects=(c_pid,))
    _no_write_anywhere(w, before)


# ── I12.6 preconditions ──────────────────────────────────────────────────────

OLD_HEAD_BREAKS = {
    "engine 0024 missing": "DELETE FROM engine.django_migrations WHERE name = '0024_no_login_of_its_own'",
    "forms migration missing": "DELETE FROM qualification._prisma_migrations"
                               " WHERE migration_name = '20260925120000_the_default_form_is_fixed'",
    "qualification migration rolled back": "UPDATE qualification._prisma_migrations SET rolled_back_at = now()"
                                           " WHERE migration_name = '20260922110000_one_naming_convention'",
    "qualification migration unfinished": "UPDATE qualification._prisma_migrations SET finished_at = NULL"
                                          " WHERE migration_name = '20260910120000_add_risks_and_airo_fields'",
    "alembic elsewhere": "UPDATE control_objectives.alembic_version SET version_num = 'b1d24aaaaaaa'",
    "composer 0005 missing": "DELETE FROM report_composer.schema_migration"
                             " WHERE name = '0005_presets_and_document_settings.sql'",
    "core 0004 missing": "DELETE FROM core.schema_migration WHERE name = '0004_card_version_of_its_project.sql'",
}


@pytest.mark.parametrize("case", sorted(OLD_HEAD_BREAKS))
def test_I12_6_source_not_at_its_old_head_refuses(make_world, rpt, case):
    S.require_tool()
    w = make_world()
    with w.source() as c:
        c.execute(OLD_HEAD_BREAKS[case])
    before = _snapshot(w)
    for sub in ("plan", "copy"):
        S.assert_refused(S.run(w, sub, "--all", report=rpt()), "source not at old head")
    _no_write_anywhere(w, before)


NEW_HEAD_BREAKS = {
    "qualification baseline missing": ("target not at new head", "DELETE FROM qualification._prisma_migrations"
                                       f" WHERE migration_name = '{S.NEW_QUALIFICATION_BASELINE}'"),
    "forms migration missing": ("target not at new head", "DELETE FROM qualification._prisma_migrations"
                                " WHERE migration_name = '20260925090000_forms_are_data'"),
    "alembic baseline missing": ("target not at new head", "DELETE FROM control_objectives.alembic_version"),
    "django 0025 missing": ("target not at new head",
                            f"DELETE FROM engine.django_migrations WHERE name = '{S.NEW_DJANGO}'"),
    "composer baseline missing": ("target not at new head", "DELETE FROM report_composer.schema_migration"),
    "controls head missing": ("target not at new head", "DELETE FROM controls._prisma_migrations"
                              " WHERE migration_name = '20260923210100_dashboard_reads_controls'"),
    "template 0009 missing": ("missing template",
                              "DELETE FROM provision.template_migration WHERE name = '0009_engine.sql'"),
}


@pytest.mark.parametrize("case", sorted(NEW_HEAD_BREAKS))
def test_I12_6_target_not_at_its_new_head_refuses_copy(make_world, rpt, case):
    S.require_tool()
    w = make_world()
    reason, stmt = NEW_HEAD_BREAKS[case]
    with w.target(w.B) as c:
        c.execute(stmt)
    before = _snapshot(w)
    S.assert_refused(S.run(w, "copy", "--all", report=rpt()), {reason, "target not at new head"},
                     projects=(w.B,))
    _no_write_anywhere(w, before)


@pytest.mark.parametrize("where", ["platform_rw on a target", "qualification_rw on the source"])
def test_I12_6_I13_4_a_module_session_refuses_copy(make_world, rpt, where):
    S.require_tool()
    w = make_world()
    if where.startswith("platform_rw"):
        dsn = make_conninfo(w.target_dsn(w.A), user="platform_rw", password="platform_rw")
    else:
        dsn = make_conninfo(w.source_dsn, user="qualification_rw", password="qualification_rw")
    before = _snapshot(w)
    with psycopg.connect(dsn, autocommit=True) as held:
        held.execute("SELECT 1")
        res = S.run(w, "copy", "--all", report=rpt())
    S.assert_refused(res, "active sessions")
    _no_write_anywhere(w, before)


COVERAGE_BREAKS = {
    "a shared column missing in the target": "ALTER TABLE qualification.qualification_answer DROP COLUMN answer",
    "a shared column of another type": "ALTER TABLE engine.aisc_backend_metric ALTER COLUMN name TYPE text",
    "a target-only column without a default": "ALTER TABLE control_objectives.risk ADD COLUMN extra text NOT NULL",
}


@pytest.mark.parametrize("case", sorted(COVERAGE_BREAKS))
def test_I12_6_target_columns_must_cover_the_source_columns(make_world, rpt, case):
    S.require_tool()
    w = make_world()
    with w.target(w.A) as c:
        c.execute(COVERAGE_BREAKS[case])
    before = _snapshot(w)
    S.assert_refused(S.run(w, "copy", "--all", report=rpt()), "column coverage")
    _no_write_anywhere(w, before)


def test_I12_6_a_target_only_column_with_a_default_is_allowed(make_world, rpt):
    S.require_tool()
    w = make_world()
    for p in w.pids:
        with w.target(p) as c:
            c.execute("ALTER TABLE control_objectives.risk ADD COLUMN extra text NOT NULL DEFAULT 'd'")
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    with w.target(w.A) as c:
        assert c.execute("SELECT DISTINCT extra FROM control_objectives.risk").fetchall() == [("d",)]


# ── I12.7 the copy itself ────────────────────────────────────────────────────


def test_I12_7_values_survive_exactly_and_checksums_are_the_spec_formula(make_world, rpt):
    """floats, bytea, jsonb, arrays and timestamps compare equal row by row; the report's md5 is
    md5(string_agg(ROW(shared columns in target order)::text, E'\\n' ORDER BY row_text))."""
    S.require_tool()
    w = make_world()
    res = S.run(w, "copy", "--all", report=rpt())
    copied(w, res)
    cases = {
        "engine.aisc_backend_measurement": ("id", [1, 2]),
        "report_composer.generated_report": ("id", [w.ids["gA"]]),
        "report_composer.template": ("id", [w.ids["tA"]]),
        "qualification.qualification": ("id", ["qA1", "qA2"]),
        "control_objectives.risk": ("id", [1, 2]),
    }
    for table, (pk, want) in cases.items():
        with w.target(w.A) as t, w.source() as s:
            cols = S.columns(t, table)
            got_t = S.checksum(t, table, cols)
            got_s = S.checksum(s, table, cols, sql.SQL("{}::text = ANY(ARRAY[{}])").format(
                sql.Identifier(pk), sql.SQL(", ").join(sql.Literal(str(v)) for v in want)))
        assert got_t == got_s, table
        entry = res.report["projects"][w.A]["tables"][table]
        assert (entry["count"], entry["target_md5"]) == got_t, table
        assert entry["source_md5"] == got_s[1], table
    # project.system: core.system minus project_id, in the target's column order
    with w.target(w.A) as t, w.source() as s:
        cols = S.columns(t, "project.system")
        got_t = S.checksum(t, "project.system", cols)
        got_s = S.checksum(s, "core.system", cols, sql.SQL("project_id = {}").format(sql.Literal(w.A)))
    assert got_t == got_s
    assert res.report["projects"][w.A]["tables"]["core.system"]["target"] == "project.system"


def test_I12_7_sequences_take_the_source_value_or_the_target_maximum(make_world, rpt):
    S.require_tool()
    w = make_world()
    res = S.run(w, "copy", "--all", report=rpt())
    copied(w, res)
    for pid, metric_max in ((w.A, 3), (w.B, 1)):
        with w.target(pid) as c:
            seq = lambda name: c.execute(sql.SQL("SELECT last_value, is_called FROM {}").format(sql.SQL(name))).fetchone()
            assert seq("control_objectives.risk_id_seq") == (10, True)
            assert seq("engine.aisc_backend_project_id_seq") == (72, True)
            assert seq("engine.aisc_backend_metric_id_seq") == (max(1, metric_max), True)
            assert seq("engine.aisc_backend_plugin_id_seq") == (30, False)
    assert res.report["projects"][w.A]["sequences"]["control_objectives.risk_id_seq"] == {
        "last_value": 10, "is_called": True}


def test_I12_7_D15_a_failure_rolls_back_that_project_and_a_rerun_resumes(make_world, rpt):
    """An interruption midway: B's insert fails (a trigger that fires even under
    session_replication_role = replica). A, first in pid order, is committed; B's database is left
    exactly as it was; after the cause is removed, the same command finishes the job."""
    S.require_tool()
    w = make_world()
    with w.target(w.B) as c:
        c.execute("CREATE FUNCTION public.boom() RETURNS trigger LANGUAGE plpgsql AS"
                  " $$ BEGIN RAISE EXCEPTION 'injected failure'; END $$")
        c.execute("CREATE TRIGGER boom BEFORE INSERT ON qualification.qualification_answer"
                  " FOR EACH ROW EXECUTE FUNCTION public.boom()")
        c.execute("ALTER TABLE qualification.qualification_answer ENABLE ALWAYS TRIGGER boom")
    b_before = S.digests(w.target_dsn(w.B))
    first = S.run(w, "copy", "--all", report=rpt())
    assert first.returncode != 0
    assert first.status(w.A) == "copied"
    assert first.status(w.B) == "failed"
    assert S.digests(w.target_dsn(w.B)) == b_before
    with w.target(w.B) as c:
        c.execute("DROP TRIGGER boom ON qualification.qualification_answer")
        c.execute("DROP FUNCTION public.boom()")
    second = S.run(w, "copy", "--all", report=rpt())
    assert second.returncode == 0, second.output[-3000:]
    assert second.status(w.A) == "already done"
    assert second.status(w.B) == "copied"
    assert S.run(w, "verify", "--all", report=rpt()).returncode == 0


# ── I12.8 idempotent, target not empty ───────────────────────────────────────


def test_I12_8_a_second_copy_is_already_done_and_writes_nothing(make_world, rpt):
    S.require_tool()
    S.quiet_cluster()
    w = make_world()
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    before = _snapshot(w)
    dbs = [w.target_db(p) for p in w.pids]
    commits = S.written_tuples(dbs)
    res = S.run(w, "copy", "--all", report=rpt())
    assert res.returncode == 0, res.output[-3000:]
    assert [res.status(p) for p in w.pids] == ["already done", "already done"]
    assert S.written_tuples(dbs) == commits, "I12.8: an already-done project must not be written"
    _no_write_anywhere(w, before)


def test_I12_8_a_target_row_that_differs_from_its_source_aborts_that_project(make_world, rpt):
    S.require_tool()
    w = make_world()
    with w.target(w.A) as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        c.execute("INSERT INTO qualification.qualification_answer VALUES ('ansA2', 'qA2', 'tool', 'q2', 'changed')")
    a_before = S.digests(w.target_dsn(w.A))
    res = S.run(w, "copy", "--all", report=rpt())
    S.assert_refused(res, "target not empty and not equal", table="qualification.qualification_answer",
                     projects=(w.A,))
    assert S.digests(w.target_dsn(w.A)) == a_before


def test_I12_8_a_target_row_unknown_to_the_source_aborts_that_project(make_world, rpt):
    S.require_tool()
    w = make_world()
    with w.target(w.A) as c:
        c.execute("INSERT INTO engine.aisc_backend_metric (id, pid, name, description, type_spec, created_at)"
                  " VALUES (99, gen_random_uuid(), 'extra', '', 's', now())")
    a_before = S.digests(w.target_dsn(w.A))
    res = S.run(w, "copy", "--all", report=rpt())
    S.assert_refused(res, "target not empty and not equal", table="engine.aisc_backend_metric", projects=(w.A,))
    assert S.digests(w.target_dsn(w.A)) == a_before


def test_I12_8_a_seed_that_differs_from_the_source_aborts(make_world, rpt):
    S.require_tool()
    w = make_world()
    with w.target(w.A) as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        c.execute("UPDATE qualification.form_version_question SET text = 'reworded'"
                  " WHERE form_version_id = 'annex-iv-default-v1' AND question_id = 'dq1'")
    res = S.run(w, "copy", "--all", report=rpt())
    S.assert_refused(res, "target not empty and not equal", table="qualification.form_version_question",
                     projects=(w.A,))


# ── I12.9 the form library, and presets (D3, D4) ─────────────────────────────


def test_I12_9_every_form_row_is_copied_to_the_library_and_the_equal_seed_is_allowed(make_world, rpt):
    S.require_tool()
    w = make_world()
    res = S.run(w, "copy", "--all", report=rpt())
    copied(w, res)
    with w.source() as c:
        for t in S.FORM_TABLES:
            cols = S.columns(c, f"form_library.{t}")
            assert S.checksum(c, f"form_library.{t}", cols) == S.checksum(c, f"qualification.{t}", cols), t
    assert res.report["library"]["status"] in {"copied", "already done"}
    again = S.run(w, "copy", "--all", report=rpt())
    assert again.report["library"]["status"] == "already done"


def test_I12_9_a_library_seed_that_differs_aborts_the_library_copy(make_world, rpt):
    S.require_tool()
    w = make_world()
    with w.source() as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        c.execute("UPDATE form_library.form SET description = 'edited' WHERE id = 'annex-iv-default'")
    before = S.digests(w.source_dsn, ("form_library",))
    res = S.run(w, "copy", "--all", report=rpt())
    S.assert_refused(res, "target not empty and not equal", table="qualification.form")
    assert S.digests(w.source_dsn, ("form_library",)) == before


def test_I12_9_D4_presets_go_to_the_report_library_and_into_no_project(make_world, rpt):
    S.require_tool()
    w = make_world()
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    with w.source() as c:
        assert c.execute("SELECT id::text, source_project_id::text FROM report_library.preset").fetchall() == [
            (w.ids["preset"], w.A)]
    for pid in w.pids:
        with w.target(pid) as c:
            assert "report_composer.preset" not in S.user_tables(c)


def test_I12_2_the_forms_tables_may_be_absent(make_world, rpt):
    """The old head before the forms migrations: nothing of forms is required or copied."""
    S.require_tool()
    w = make_world(forms=False)
    res = S.run(w, "copy", "--all", report=rpt())
    copied(w, res)
    assert target_keys(w, w.A, "qualification.qualification") == {"qA1", "qA2"}
    assert S.run(w, "verify", "--all", report=rpt()).returncode == 0


# ── I12.10, I12.13 verification ──────────────────────────────────────────────


def test_I12_10_verify_catches_a_target_row_corrupted_after_the_copy(make_world, rpt):
    S.require_tool()
    w = make_world()
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    assert S.run(w, "verify", "--all", report=rpt()).returncode == 0
    with w.target(w.A) as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        c.execute("UPDATE qualification.qualification_answer SET answer = 'tampered' WHERE id = 'ansA2'")
    res = S.run(w, "verify", "--all", report=rpt())
    S.assert_refused(res, "checksum mismatch", table="qualification.qualification_answer", projects=(w.A,))


def test_I12_10_verify_catches_a_target_row_that_went_missing(make_world, rpt):
    S.require_tool()
    w = make_world()
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    with w.target(w.B) as c:
        c.execute("DELETE FROM control_objectives.risk WHERE id = 3")
    S.assert_refused(S.run(w, "verify", "--all", report=rpt()), "count mismatch",
                     table="control_objectives.risk", projects=(w.B,))


def test_I12_10_the_checksum_does_not_depend_on_physical_row_order(make_world, rpt):
    S.require_tool()
    w = make_world()
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    with w.target(w.A) as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        rows = c.execute("SELECT * FROM qualification.qualification_answer ORDER BY id DESC").fetchall()
        c.execute("DELETE FROM qualification.qualification_answer")
        for r in rows:
            c.execute("INSERT INTO qualification.qualification_answer VALUES (%s, %s, %s, %s, %s)", r)
    assert S.run(w, "verify", "--all", report=rpt()).returncode == 0


def test_I12_13_verify_accounts_for_every_source_row(make_world, rpt):
    S.require_tool()
    w = make_world()
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    res = S.run(w, "verify", "--all", report=rpt())
    assert res.returncode == 0, res.output[-3000:]
    cov = res.report["coverage"]
    with w.source() as c:
        for t in moving_tables(c):
            n = c.execute(sql.SQL("SELECT count(*) FROM {}").format(sql.SQL(t))).fetchone()[0]
            assert cov[t]["source_rows"] == n, t
            assert cov[t]["covered"] == n and cov[t]["missing"] == 0, t
    assert all(p["status"] == "verified" for p in res.report["projects"].values())


def test_I12_13_verify_flags_a_source_row_that_no_target_holds(make_world, rpt):
    S.require_tool()
    w = make_world()
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    with w.source() as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        c.execute("INSERT INTO qualification.qualification_answer VALUES ('ansA9', 'qA2', 'tool', 'q9', 'late')")
    res = S.run(w, "verify", "--all", report=rpt())
    S.assert_refused(res, {"count mismatch", "checksum mismatch"}, table="qualification.qualification_answer",
                     projects=(w.A,))


# ── I12.11, I12.12 no writes where none are allowed ──────────────────────────


def test_I12_11_copy_never_writes_deletes_or_locks_the_source(make_world, rpt):
    """While another session holds every moving table in EXCLUSIVE mode (which lets plain SELECTs
    through and blocks every INSERT, UPDATE, DELETE and SELECT ... FOR UPDATE/SHARE), the copy
    completes; afterwards every source table has the same checksum and no tuple counter moved."""
    S.require_tool()
    w = make_world()
    schemas = S.MOVING_SCHEMAS + ("core",)
    digests_before = S.digests(w.source_dsn, schemas)
    counters_before = S.tuple_counters(w.source_dsn, schemas)
    with w.source() as holder:
        tables = moving_tables(holder) + ["core.project", "core.project_member", "core.schema_migration"]
        holder.execute("BEGIN")
        holder.execute(sql.SQL("LOCK TABLE {} IN EXCLUSIVE MODE").format(
            sql.SQL(", ").join(sql.SQL(t) for t in tables)))
        res = S.run(w, "copy", "--all", report=rpt(), timeout=180)
        holder.execute("ROLLBACK")
    copied(w, res)
    assert S.digests(w.source_dsn, schemas) == digests_before
    assert S.tuple_counters(w.source_dsn, schemas) == counters_before


@pytest.mark.parametrize("argv", [("plan", "--all"), ("copy", "--all", "--dry-run")])
def test_I12_12_plan_and_dry_run_compute_everything_and_write_nothing(make_world, rpt, argv):
    S.require_tool()
    S.quiet_cluster()
    w = make_world()
    before = _snapshot(w)
    dbs = [w.target_db(p) for p in w.pids]
    commits = S.written_tuples(dbs)
    res = S.run(w, *argv, report=rpt())
    assert res.returncode == 0, res.output[-3000:]
    assert S.written_tuples(dbs) == commits
    _no_write_anywhere(w, before)
    a = res.report["projects"][w.A]
    assert a["status"] == "planned"
    answers = a["tables"]["qualification.qualification_answer"]
    assert (answers["source_rows"], answers["to_copy"], answers["already_present"]) == (4, 3, 0)
    forms = a["tables"]["qualification.form"]
    assert (forms["to_copy"], forms["already_present"]) == (1, 1)  # the equal seed
    assert "control_objectives.risk_id_seq" in a["sequences"]
    assert res.report["unowned"] and res.report["refusals"] == []


# ── I12.14 verify-dump ───────────────────────────────────────────────────────


def _docker_pg(tmp_path: Path) -> Path:
    """pg_dump/pg_restore of postgres:14-alpine on the host network (the host has no client)."""
    if not shutil.which("docker"):
        pytest.skip("docker is needed to run pg_dump/pg_restore for I12.14")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("pg_dump", "pg_restore"):
        shim = bin_dir / tool
        shim.write_text(
            "#!/bin/sh\n"
            f'exec docker run --rm -i --network host -v "{tmp_path}:{tmp_path}" postgres:14-alpine {tool} "$@"\n')
        shim.chmod(0o755)
    return bin_dir


def test_I12_14_verify_dump_proves_the_stage_7_dump_row_by_row(make_world, rpt, tmp_path):
    S.require_tool()
    w = make_world()
    bin_dir = _docker_pg(tmp_path)
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    # Two files: pg_dump ignores -n when -t is given, so I15.2's single command would dump
    # core.system alone (spec gap recorded in 02-tests.md).
    schemas, system = tmp_path / "schemas.dump", tmp_path / "core_system.dump"
    subprocess.run([str(bin_dir / "pg_dump"), "-Fc", "-n", "qualification", "-n", "control_objectives",
                    "-n", "engine", "-n", "report_composer", "-f", str(schemas), w.source_dsn],
                   check=True, capture_output=True)
    subprocess.run([str(bin_dir / "pg_dump"), "-Fc", "-t", "core.system", "-f", str(system), w.source_dsn],
                   check=True, capture_output=True)
    env = {"PATH": f"{bin_dir}:{os.environ['PATH']}"}
    databases = lambda: {r[0] for r in psycopg.connect(S.dsn_for("postgres"), autocommit=True).execute(
        "SELECT datname FROM pg_database").fetchall()}
    dbs_before = databases()
    ok = S.run(w, "verify-dump", "--all", str(schemas), str(system), report=rpt(), env=env)
    assert ok.returncode == 0, ok.output[-3000:]
    with w.target(w.A) as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        c.execute("UPDATE engine.aisc_backend_measurement SET score = 0.5 WHERE id = 1")
    bad = S.run(w, "verify-dump", "--all", str(schemas), str(system), report=rpt(), env=env)
    S.assert_refused(bad, "checksum mismatch", table="engine.aisc_backend_measurement", projects=(w.A,))
    assert databases() == dbs_before, "verify-dump left its restore database behind"


# ── I12.15, I12.16 report and logs ───────────────────────────────────────────


def test_I12_15_the_report_holds_keys_and_counts_never_row_values(make_world, rpt):
    S.require_tool()
    w = make_world()
    path = rpt("copy")
    res = S.run(w, "copy", "--all", report=path)
    copied(w, res)
    text = path.read_text()
    for value in ("answer " + w.mark, "enc-", "Custom one", "Alpha", "Beta", "2*x", "%PDF"):
        assert value not in text, value
    assert oct(path.stat().st_mode & 0o777) == "0o600", "I13.3: reports are written mode 600"
    rep = json.loads(text)
    assert rep["snapshot_time"]
    t = rep["projects"][w.A]["tables"]["qualification.qualification_answer"]
    assert {"target", "source_rows", "to_copy", "already_present", "copied", "count",
            "source_md5", "target_md5"} <= set(t)
    assert t["target"] == "qualification.qualification_answer" and t["copied"] == 3
    assert res.stdout.strip(), "I12.15: a human summary on stdout"
    assert w.A in res.stdout


def test_I12_16_refusals_exit_non_zero_and_output_names_pids_and_counts_only(make_world, rpt):
    S.require_tool()
    w = make_world()
    with w.source() as c, c.transaction():
        c.execute("SET LOCAL session_replication_role = replica")
        c.execute("UPDATE engine.aisc_backend_evaluation SET system_id = %s WHERE id = 1", (w.ids["sB1"],))
    res = S.run(w, "copy", "--all", report=rpt())  # S.run asserts no value/credential leaked
    assert res.returncode != 0
    for value in ("Scorer", "card sA", "alice", "Alpha"):
        assert value not in res.output, value
    res = S.run(w, "copy", "--project", "not-a-pid", report=rpt())
    assert res.returncode != 0


def test_I12_16_one_project_at_a_time_on_request(make_world, rpt):
    S.require_tool()
    w = make_world()
    res = S.run(w, "copy", "--project", w.B, report=rpt())
    assert res.returncode == 0, res.output[-3000:]
    assert res.status(w.B) == "copied" and w.A not in res.report["projects"]
    assert target_keys(w, w.A, "qualification.qualification") == set()


# ── the other subcommands ────────────────────────────────────────────────────


def test_I12_C6_provision_makes_a_missing_project_database_with_every_template_file(make_world, rpt):
    S.require_tool()
    w = make_world()
    c_pid = "eeeeeeee-eeee-4eee-beee-" + uuid.uuid4().hex[:12]
    w.ids["_extra_dbs"] = [S.projectdb.database_name(c_pid)]
    with w.source() as c:
        c.execute("INSERT INTO core.project (pid, name, slug) VALUES (%s, 'Gamma', %s)", (c_pid, f"iso-c-{w.tag}"))
    for _ in range(2):  # idempotent
        res = S.run(w, "provision", "--project", c_pid, report=rpt())
        assert res.returncode == 0, res.output[-3000:]
    want = {p.name for p in S.projectdb.TEMPLATE.glob("*.sql")}
    with psycopg.connect(S.dsn_for(S.projectdb.database_name(c_pid)), autocommit=True) as c:
        assert {r[0] for r in c.execute("SELECT name FROM provision.template_migration")} == want
        owner = c.execute("SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()").fetchone()
    assert owner == ("platform_rw",)


def test_I12_15_report_subcommand_summarises_without_writing(make_world, rpt):
    S.require_tool()
    w = make_world()
    copied(w, S.run(w, "copy", "--all", report=rpt()))
    before = _snapshot(w)
    res = S.run(w, "report", "--all", report=rpt())
    assert res.returncode == 0, res.output[-3000:]
    t = res.report["projects"][w.A]["tables"]["engine.aisc_backend_measurement"]
    assert t["count"] == 2 and t["source_md5"] == t["target_md5"]
    _no_write_anywhere(w, before)
