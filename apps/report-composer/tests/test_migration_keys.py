"""The keys of the composer's tables into core (migrations 0003 and 0004).

0003: a generated report points at its project and its version the way its layout does.
0004: a layout's and a report's version belong to their project: (system_id, project_id)
      references core.system (pid, project_id), which the platform makes unique. Where the
      platform has not made it yet, 0004 leaves the keys out and init/project-databases.sql
      adds them under the same names on its next run.

Database tests on the bed; migrations run when the app starts, so each test takes `client`.
"""
import json
from pathlib import Path

import pytest

from conftest import IDS

pytestmark = [pytest.mark.db, pytest.mark.usefixtures("clean_layouts")]

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
M0004 = MIGRATIONS / "0004_a_version_of_its_project.sql"
LAYOUT = "10000000-0000-4000-8000-0000000000c1"
NOWHERE = "deadbeef-0000-4000-8000-00000000dead"


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


def test_0003_the_report_points_at_its_project_and_version_as_its_layout_does(client, bed):
    client.get("/api/block-types")
    layout, report = keys(bed, "layout"), keys(bed, "generated_report")
    assert report["generated_report_project_id_fkey"] == layout["layout_project_id_fkey"]
    assert report["generated_report_project_id_fkey"] == (
        "FOREIGN KEY (project_id) REFERENCES core.project(pid) ON DELETE CASCADE", "c")
    # the layout's system key has no ON DELETE rule (NO ACTION), and so has the report's
    assert report["generated_report_system_id_fkey"] == layout["layout_system_id_fkey"]
    assert report["generated_report_system_id_fkey"] == (
        "FOREIGN KEY (system_id) REFERENCES core.system(pid)", "a")
    assert report["generated_report_layout_id_fkey"][1] == "c"


def test_0003_a_report_of_no_project_is_refused(client, bed):
    client.get("/api/block-types")
    assert layout_row(bed).returncode == 0
    r = report_row(bed, project=NOWHERE)
    assert r.returncode != 0 and "generated_report_project_id_fkey" in r.stderr


def test_0003_a_report_of_no_version_is_refused(client, bed):
    client.get("/api/block-types")
    assert layout_row(bed).returncode == 0
    r = report_row(bed, system=NOWHERE)
    assert r.returncode != 0 and "generated_report_system_id_fkey" in r.stderr


# ── 0004: the version belongs to the project ────────────────────────────────


def test_0004_the_pair_is_a_key_into_core_system(client, bed):
    client.get("/api/block-types")
    pair = "FOREIGN KEY (system_id, project_id) REFERENCES core.system(pid, project_id)"
    assert keys(bed, "layout")["layout_system_id_project_id_fkey"] == (pair, "a")
    assert keys(bed, "generated_report")["generated_report_system_id_project_id_fkey"] == (pair, "a")


def test_0004_a_layout_of_a_version_of_another_project_is_refused(client, bed):
    client.get("/api/block-types")
    r = layout_row(bed, system=IDS["B_V1"])
    assert r.returncode != 0 and "layout_system_id_project_id_fkey" in r.stderr


def test_0004_a_report_of_a_version_of_another_project_is_refused(client, bed):
    client.get("/api/block-types")
    assert layout_row(bed).returncode == 0
    r = report_row(bed, system=IDS["B_V1"])
    assert r.returncode != 0 and "generated_report_system_id_project_id_fkey" in r.stderr


def test_0004_without_the_platform_unique_it_leaves_the_keys_out_and_succeeds(client, bed):
    client.get("/api/block-types")
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


def test_0004_run_again_changes_nothing(client, bed):
    client.get("/api/block-types")
    r = bed.psql("platform", f"""
        BEGIN;
        {M0004.read_text()}
        SELECT 'keys=' || count(*) FROM pg_constraint
         WHERE conname IN ('layout_system_id_project_id_fkey', 'generated_report_system_id_project_id_fkey');
        ROLLBACK;""", check=False)
    assert r.returncode == 0, r.stderr
    assert "keys=2" in r.stdout
