"""The keys of the composer's tables into core (migrations 0003 and 0004).

0003: a generated report points at its project and its version the way its layout does.
0004: a layout's and a report's version belong to their project: (system_id, project_id)
      references core.system (pid, project_id), which the platform makes unique. Where the
      platform has not made it yet, 0004 leaves the keys out and init/project-databases.sql
      adds them under the same names on its next run.

Isolation 2026-09-25 (S-D13): the composer itself no longer runs these files; they are the
pre-isolation history of the shared schema, kept in pre_isolation_migrations/ because cutover step C4
still applies 0003..0005 to the live shared schema before the data move. So this file keeps pinning
them on the OLD shared layout: its own bed (report_bed.build, the pre-isolation platform), the files
applied with the composer's generic runner as report_composer_rw (what C4 does), instead of starting
the app. Every assertion is unchanged; each test takes `migrated` where it took `client`.
"""
import json
import sys
from pathlib import Path

import psycopg
import pytest

from conftest import IDS, ROOT

sys.path.insert(0, str(ROOT / "scripts/lib"))
import report_bed  # noqa: E402

pytestmark = [pytest.mark.db]

APP = Path(__file__).resolve().parents[1]
MIGRATIONS = APP / "pre_isolation_migrations"
M0004 = MIGRATIONS / "0004_a_version_of_its_project.sql"
LAYOUT = "10000000-0000-4000-8000-0000000000c1"
NOWHERE = "deadbeef-0000-4000-8000-00000000dead"


@pytest.fixture(scope="module")
def keys_bed():
    """The pre-isolation shared layout with the composer's old history applied to `platform`."""
    report_bed.check_dsn_env()
    b = report_bed.build("composer-keys", modules=False)
    try:
        from report_composer.migrate import migrate

        with psycopg.connect(b.dsn("report_composer_rw", "platform")) as conn:
            migrate(conn, directory=MIGRATIONS)
        yield b
    finally:
        b.stop()


@pytest.fixture
def bed(keys_bed):
    """This module's bed (it overrides the conftest's isolated one); every test starts without layouts."""
    keys_bed.psql("platform", "TRUNCATE report_composer.layout, report_composer.template CASCADE")
    return keys_bed


@pytest.fixture
def migrated(bed):
    """The pre-isolation files are applied (by `keys_bed`), as the app's start applied them before."""
    return bed


def keys(bed, table):
    # jsonb, not json: json_agg puts a newline between rows, and the bed reads one line
    rows = json.loads(bed.scalar(
        "platform",
        "SELECT coalesce(jsonb_agg(t), '[]') FROM (SELECT conname, pg_get_constraintdef(oid) AS def,"
        f" confdeltype::text AS del FROM pg_constraint WHERE conrelid = 'report_composer.{table}'::regclass"
        " AND contype = 'f') t"))
    return {r["conname"]: (r["def"], r["del"]) for r in rows}


def layout_row(bed, project=IDS["A"], system=IDS["A_V2"]):
    return bed.psql("platform", "INSERT INTO report_composer.layout (id, project_id, system_id, name, created_by,"
                    f" updated_by) VALUES ('{LAYOUT}', '{project}', '{system}', 'L', 'alice', 'alice')", check=False)


def report_row(bed, project=IDS["A"], system=IDS["A_V2"]):
    return bed.psql("platform", "INSERT INTO report_composer.generated_report (layout_id, layout_revision,"
                    " project_id, system_id, snapshot, status, created_by) VALUES"
                    f" ('{LAYOUT}', 1, '{project}', '{system}', '{{}}', 'running', 'alice')", check=False)


# ── 0003: the report's keys match the layout's ──────────────────────────────


def test_0003_the_report_points_at_its_project_and_version_as_its_layout_does(migrated, bed):
    layout, report = keys(bed, "layout"), keys(bed, "generated_report")
    assert report["generated_report_project_id_fkey"] == layout["layout_project_id_fkey"]
    assert report["generated_report_project_id_fkey"] == (
        "FOREIGN KEY (project_id) REFERENCES core.project(pid) ON DELETE CASCADE", "c")
    # the layout's system key has no ON DELETE rule (NO ACTION), and so has the report's
    assert report["generated_report_system_id_fkey"] == layout["layout_system_id_fkey"]
    assert report["generated_report_system_id_fkey"] == (
        "FOREIGN KEY (system_id) REFERENCES core.system(pid)", "a")
    assert report["generated_report_layout_id_fkey"][1] == "c"


def test_0003_a_report_of_no_project_is_refused(migrated, bed):
    assert layout_row(bed).returncode == 0
    r = report_row(bed, project=NOWHERE)
    assert r.returncode != 0 and "generated_report_project_id_fkey" in r.stderr


def test_0003_a_report_of_no_version_is_refused(migrated, bed):
    assert layout_row(bed).returncode == 0
    r = report_row(bed, system=NOWHERE)
    assert r.returncode != 0 and "generated_report_system_id_fkey" in r.stderr


# ── 0004: the version belongs to the project ────────────────────────────────


def test_0004_the_pair_is_a_key_into_core_system(migrated, bed):
    pair = "FOREIGN KEY (system_id, project_id) REFERENCES core.system(pid, project_id)"
    assert keys(bed, "layout")["layout_system_id_project_id_fkey"] == (pair, "a")
    assert keys(bed, "generated_report")["generated_report_system_id_project_id_fkey"] == (pair, "a")


def test_0004_a_layout_of_a_version_of_another_project_is_refused(migrated, bed):
    r = layout_row(bed, system=IDS["B_V1"])
    assert r.returncode != 0 and "layout_system_id_project_id_fkey" in r.stderr


def test_0004_a_report_of_a_version_of_another_project_is_refused(migrated, bed):
    assert layout_row(bed).returncode == 0
    r = report_row(bed, system=IDS["B_V1"])
    assert r.returncode != 0 and "generated_report_system_id_project_id_fkey" in r.stderr


def test_0004_without_the_platform_unique_it_leaves_the_keys_out_and_succeeds(migrated, bed):
    assert M0004.exists()
    r = bed.psql("platform", f"""
        BEGIN;
        ALTER TABLE report_composer.layout DROP CONSTRAINT layout_system_id_project_id_fkey;
        ALTER TABLE report_composer.generated_report DROP CONSTRAINT generated_report_system_id_project_id_fkey;
        ALTER TABLE core.system DROP CONSTRAINT system_pid_project_id_key;
        {M0004.read_text()}
        SELECT 'keys=' || count(*) FROM pg_constraint
         WHERE conname IN ('layout_system_id_project_id_fkey', 'generated_report_system_id_project_id_fkey');
        ROLLBACK;""", check=False)
    assert r.returncode == 0, r.stderr
    assert "keys=0" in r.stdout


def test_0004_run_again_changes_nothing(migrated, bed):
    r = bed.psql("platform", f"""
        BEGIN;
        {M0004.read_text()}
        SELECT 'keys=' || count(*) FROM pg_constraint
         WHERE conname IN ('layout_system_id_project_id_fkey', 'generated_report_system_id_project_id_fkey');
        ROLLBACK;""", check=False)
    assert r.returncode == 0, r.stderr
    assert "keys=2" in r.stdout
