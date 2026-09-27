"""The report test bed: one throwaway Postgres with every database the report reads.

Design: docs/superpowers/report-2026-09-23/02-architecture.md, section 5. Used by the
renderer's tests (aisc-report-generator), the composer's tests (apps/report-composer) and the
stack tests (scripts/tests). Test infrastructure only: it builds data, it implements nothing of
the report.

    from report_bed import build
    bed = build("renderer")        # postgres:14-alpine, aisc-t-renderer-<hex>, a free port
    bed.dsn("report_ro", "platform")
    bed.stop()

What it builds, in order (each step as the stack does it):
 1. init/platform-db.sql, init/project-databases.sql, init/superset-db.sql (superuser)
 2. init/report-roles.sql (superuser), when present and report_files is on
 3. platform migrations 0001.. as platform_rw
 4. the module schemas from the read-only dumps in scripts/tests/fixtures/report/, each restored
    as its own module role (so ownership is as on the stack), and superset's as the superuser
 5. project databases of Alpha, Beta, Echo, Mike and Delta as platform_rw with platform/project-template/*.sql
    (every template file, 0003_report.sql included), then schema controls as controls_rw
 6. scripts/report-grants.sh, when present and report_files is on, run inside the container
    like the stack's report-grants one-shot: PG* env, init/report-ro-grants.sql copied to /setup
 7. the seed (fixtures/report/seed_*.sql), as the superuser

Never the host's 5432: the port is one the kernel picks, and `check_dsn_env` refuses to go on
when a DSN variable a test reads points anywhere else.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "scripts/tests/fixtures/report"
sys.path.insert(0, str(ROOT / "scripts/pipeline_chain"))
from throwaway import Throwaway, platform_migration  # noqa: E402

REPORT_ROLES_SQL = ROOT / "init/report-roles.sql"
REPORT_GRANTS_SQL = ROOT / "init/report-ro-grants.sql"
REPORT_GRANTS_SH = ROOT / "scripts/report-grants.sh"
PROJECT_TEMPLATE = ROOT / "platform/project-template"

#: Fixed ids of the seed. Version 2 of Alpha is the usual pinned version.
IDS = {
    "A": "a0000000-0000-4000-8000-000000000001",
    "A_V1": "a1000000-0000-4000-8000-000000000001",
    "A_V2": "a2000000-0000-4000-8000-000000000002",
    "A_V3": "a3000000-0000-4000-8000-000000000003",
    "B": "b0000000-0000-4000-8000-000000000001",
    "B_V1": "b1000000-0000-4000-8000-000000000001",
    "C": "c0000000-0000-4000-8000-000000000001",
    "C_V1": "c1000000-0000-4000-8000-000000000001",
    "E": "e0000000-0000-4000-8000-000000000001",
    "E_V1": "e1000000-0000-4000-8000-000000000001",
    "E_V2": "e2000000-0000-4000-8000-000000000002",
    # engine evaluation pids
    "EVAL_A_V1": "a1e00000-0000-4000-8000-000000000011",
    "EVAL_A_V2": "a2e00000-0000-4000-8000-000000000021",
    "EVAL_A_V2_FAILED": "a2e00000-0000-4000-8000-000000000022",
    "EVAL_A_V2_NOCONFIG": "a2e00000-0000-4000-8000-000000000023",
    "EVAL_A_V3": "a3e00000-0000-4000-8000-000000000031",
    "EVAL_A_NULL": "a0e00000-0000-4000-8000-000000000041",
    "EVAL_B_V1": "b1e00000-0000-4000-8000-000000000051",
    "EVAL_E_V1": "e1e00000-0000-4000-8000-000000000061",
    "EVAL_E_V2": "e2e00000-0000-4000-8000-000000000062",
    # report run v2 (seed_tools.sql): project Mike with the three Mijke tools, project Delta with no evaluation
    "M": "f0000000-0000-4000-8000-000000000001",
    "M_V1": "f1000000-0000-4000-8000-000000000001",
    "M_V2": "f2000000-0000-4000-8000-000000000002",
    "D": "d0000000-0000-4000-8000-000000000001",
    "D_V1": "d1000000-0000-4000-8000-000000000001",
    "EVAL_M_V1": "f1e00000-0000-4000-8000-000000000070",
    "EVAL_M_V2_SR_FAILED": "f2e00000-0000-4000-8000-000000000071",
    "EVAL_M_V2_LB_SR": "f2e00000-0000-4000-8000-000000000072",
    "EVAL_M_V2_PF_PARTIAL": "f2e00000-0000-4000-8000-000000000073",
    "EVAL_M_V2_PF_FULL": "f2e00000-0000-4000-8000-000000000074",
    "EVAL_M_V2_PF_FAILED": "f2e00000-0000-4000-8000-000000000075",
    # superset chart ids
    "CHART_A": 33,
    "CHART_A2": 34,
    "CHART_B": 35,
    "CHART_E": 36,
}
SLUGS = {"A": "alpha", "B": "beta", "C": "gamma", "E": "echo", "M": "mike", "D": "delta"}
#: Texts that belong to data a report pinned to Alpha v2 must never show.
FOREIGN_MARKERS = ("V1MARK", "V3MARK", "NULLMARK", "BETAMARK")

#: DSN variables any report test may read. All must point at the bed, or be unset.
DSN_ENV_VARS = (
    "REPORT_PLATFORM_DATABASE_URL", "REPORT_SUPERSET_DATABASE_URL", "REPORT_PROJECT_DB_URL",
    "REPORT_COMPOSER_DATABASE_URL", "DATABASE_URL", "PLATFORM_DATABASE_URL",
    "PLATFORM_TEST_DATABASE_URL", "DB_URL",
)


def hex_of(pid: str) -> str:
    return pid.replace("-", "")


def project_db(pid: str) -> str:
    return "project_" + hex_of(pid)


def check_dsn_env(port: int | None = None) -> None:
    """Refuse to run when a DSN variable points at anything but the bed (never the live 5432)."""
    for name in DSN_ENV_VARS:
        value = os.environ.get(name)
        if not value:
            continue
        if ":5432/" in value or (port is not None and f":{port}/" not in value):
            raise RuntimeError(f"{name} points outside the test bed; unset it before running the tests")


@dataclass
class ReportBed:
    t: Throwaway
    #: which of the report's grant files (report-roles.sql, report-grants.sh) the bed applied
    applied: dict[str, bool] = field(default_factory=dict)
    ids: dict = field(default_factory=lambda: dict(IDS))

    @property
    def port(self) -> int:
        return self.t.port

    def dsn(self, role: str, db: str, password: str | None = None) -> str:
        return f"postgresql://{role}:{password or role}@127.0.0.1:{self.t.port}/{db}"

    def su_dsn(self, db: str) -> str:
        return f"postgresql://aisc-postgres-user:{self.t.password}@127.0.0.1:{self.t.port}/{db}"

    def project_db_template(self, role: str = "report_ro") -> str:
        """A DSN with `{database}` in place of the name, as REPORT_PROJECT_DB_URL."""
        return f"postgresql://{role}:{role}@127.0.0.1:{self.t.port}/{{database}}"

    def psql(self, db: str, sql: str, role: str | None = None, check: bool = True):
        return self.t.psql(db, sql, role=role, check=check)

    def rows(self, db: str, sql: str, role: str | None = None) -> list[dict]:
        return self.t.rows(db, sql, role=role)

    def scalar(self, db: str, sql: str) -> str:
        return self.t.scalar(db, sql)

    def stop(self) -> None:
        self.t.stop()

    def env(self) -> dict[str, str]:
        """The renderer's environment on this bed."""
        return {
            "REPORT_PLATFORM_DATABASE_URL": self.dsn("report_ro", "platform"),
            "REPORT_SUPERSET_DATABASE_URL": self.dsn("report_ro", "superset"),
            "REPORT_PROJECT_DB_URL": self.project_db_template(),
            "REPORT_AIRO_VOCAB_PATH": str(FIXTURES / "airo_vocab.json"),
            "REPORT_OBJECTIVES_CSV_PATH": str(FIXTURES / "ai_act_control_objectives.csv"),
        }


def _run(t: Throwaway, db: str, sql: str, role: str | None, what: str) -> None:
    r = t.psql(db, sql, role=role, check=False)
    if r.returncode != 0:
        raise RuntimeError(f"bed: {what} failed on {db} as {role or 'superuser'}:\n{r.stderr[-3000:]}")


def _su_file(t: Throwaway, db: str, path: Path) -> None:
    _run(t, db, path.read_text(), None, path.name)


def _as_file(t: Throwaway, db: str, role: str, path: Path, prefix: str = "") -> None:
    _run(t, db, prefix + path.read_text(), role, path.name)


def _project_database(t: Throwaway, pid: str) -> str:
    """As platform_service.projectdb.provision: made by platform_rw, template applied as it."""
    name = project_db(pid)
    t.psql("platform", f'CREATE DATABASE "{name}"', role="platform_rw")
    t.psql(name, "CREATE SCHEMA IF NOT EXISTS provision;\n"
           "CREATE TABLE IF NOT EXISTS provision.template_migration (name text PRIMARY KEY,"
           " applied_at timestamptz NOT NULL DEFAULT now());", role="platform_rw")
    for f in sorted(PROJECT_TEMPLATE.glob("*.sql")):
        t.psql(name, f.read_text() + f"\n;\nINSERT INTO provision.template_migration (name) VALUES ('{f.name}');",
               role="platform_rw")
    _as_file(t, name, "controls_rw", FIXTURES / "schema_controls.sql")
    return name


def run_report_grants(t: Throwaway) -> subprocess.CompletedProcess:
    """scripts/report-grants.sh inside the container, the way the report-grants one-shot runs it."""
    subprocess.run(["docker", "exec", t.name, "mkdir", "-p", "/setup"], check=True, capture_output=True)
    for src in (REPORT_GRANTS_SH, REPORT_GRANTS_SQL):
        if src.exists():
            subprocess.run(["docker", "cp", str(src), f"{t.name}:/setup/{src.name}"], check=True,
                           capture_output=True)
    return subprocess.run(
        ["docker", "exec", "-e", "PGHOST=127.0.0.1", "-e", "PGUSER=aisc-postgres-user",
         "-e", f"PGPASSWORD={t.password}", "-e", "PGDATABASE=platform",
         "-e", "REPORT_GRANTS_WAIT_SECONDS=5", t.name, "sh", "/setup/report-grants.sh"],
        capture_output=True, text=True, timeout=300)


def build(label: str = "report", *, seed: bool = True, modules: bool = True,
          report_files: bool = True) -> ReportBed:
    t = Throwaway.start(label)
    bed = ReportBed(t)
    try:
        check_dsn_env(t.port)
        _su_file(t, "postgres", ROOT / "init/platform-db.sql")
        _su_file(t, "platform", ROOT / "init/project-databases.sql")
        _su_file(t, "postgres", ROOT / "init/superset-db.sql")
        bed.applied["report-roles.sql"] = report_files and REPORT_ROLES_SQL.exists()
        if bed.applied["report-roles.sql"]:
            _su_file(t, "platform", REPORT_ROLES_SQL)
        for m in sorted((ROOT / "platform/migrations").glob("*.sql")):
            platform_migration(t, m)
        if modules:
            for schema, role in (("qualification", "qualification_rw"),
                                 ("control_objectives", "control_objectives_rw"),
                                 ("engine", "engine_rw")):
                _as_file(t, "platform", role, FIXTURES / f"schema_{schema}.sql")
            _su_file(t, "superset", FIXTURES / "schema_superset.sql")
            for key in ("A", "B", "E", "M", "D"):
                _project_database(t, IDS[key])
            bed.applied["report-grants.sh"] = report_files and REPORT_GRANTS_SH.exists()
            if bed.applied["report-grants.sh"]:
                r = run_report_grants(t)
                if r.returncode != 0:
                    raise RuntimeError("report-grants.sh failed:\n" + r.stdout[-2000:] + r.stderr[-2000:])
            if seed:
                _su_file(t, "platform", FIXTURES / "seed_platform.sql")
                _su_file(t, "superset", FIXTURES / "seed_superset.sql")
                _su_file(t, project_db(IDS["A"]), FIXTURES / "seed_controls_alpha.sql")
                _su_file(t, project_db(IDS["B"]), FIXTURES / "seed_controls_beta.sql")
                _su_file(t, project_db(IDS["E"]), FIXTURES / "seed_controls_echo.sql")
                # report run v2: the Mijke tools (Mike) and a version with no evaluation (Delta)
                _su_file(t, "platform", FIXTURES / "seed_tools.sql")
                _su_file(t, project_db(IDS["M"]), FIXTURES / "seed_controls_mike.sql")
                _su_file(t, project_db(IDS["D"]), FIXTURES / "seed_controls_delta.sql")
        elif seed:
            # core only (the composer's bed): the projects, versions and members
            core = (FIXTURES / "seed_platform.sql").read_text().split("-- ── qualification")[0]
            t.psql("platform", core)
        return bed
    except Exception:
        t.stop()
        raise


if __name__ == "__main__":  # a smoke run: build, print a count, remove
    b = build("bed-smoke")
    try:
        print("applied:", b.applied)
        print("evaluations:", b.scalar("platform", "SELECT count(*) FROM engine.evaluation"))
        print("answers A:", b.scalar(project_db(IDS["A"]), "SELECT count(*) FROM controls.submission_answer"))
        print("comments:", b.scalar("superset", "SELECT count(*) FROM aisc_comment"))
    finally:
        b.stop()
