"""scripts/verify-project-databases.sh, the "done" check of the isolation (01-specs.md I16.1..I16.7, I19.1).

Static checks on the script, then runs against the isolation bed (two throwaway project databases, every
module migrated, never the host's 5432). The script reads its cluster from the PG* environment (like
scripts/verify-db-consistency.sh), so a test points it at the throwaway; the container part (I16.4
docker inspect) and the functional API part (I16.5) are switched off here with VERIFY_SKIP_CONTAINERS=1
and VERIFY_SKIP_FUNCTIONAL=1 and checked statically (decision recorded in 02-tests.md).
"""

from __future__ import annotations

import os
import re
import subprocess
from contextlib import contextmanager

import pytest

import isolation_bed as ib
from conftest import ROOT

SCRIPT = ROOT / "scripts/verify-project-databases.sh"
VERIFY = ROOT / "scripts/verify.sh"
DB_ACCESS = ROOT / "scripts/verify-db-access.sh"
DB_A = ib.project_db(ib.A)


def body() -> str:
    assert SCRIPT.exists(), "I16: scripts/verify-project-databases.sh missing"
    return "\n".join(l for l in SCRIPT.read_text().splitlines() if not l.lstrip().startswith("#"))


# ── static ───────────────────────────────────────────────────────────────────


def test_i16_the_script_exists_and_is_executable():
    assert SCRIPT.exists(), "I16: scripts/verify-project-databases.sh missing"
    assert os.access(SCRIPT, os.X_OK), "I16: verify-project-databases.sh is not executable"


def test_i19_1_verify_sh_runs_it_instead_of_verify_one_database():
    text = VERIFY.read_text()
    assert "verify-project-databases.sh" in text, "I19.1: verify.sh does not run verify-project-databases.sh"
    assert "verify-one-database.sh" not in text, "I19.1: verify.sh still runs verify-one-database.sh"


def test_i16_the_script_is_read_only():
    """I16: read-only sessions and no statement that changes anything."""
    b = body()
    assert "default_transaction_read_only" in b, "I16: the script's sessions are not read-only"
    for stmt in (r"\bGRANT\b", r"\bREVOKE\b", r"\bALTER\s+(TABLE|ROLE|SCHEMA|DATABASE)\b", r"\bDROP\s",
                 r"\bTRUNCATE\b", r"\bDELETE\s+FROM\b", r"\bINSERT\s+INTO\b", r"\bUPDATE\s+\w+\s+SET\b"):
        assert not re.search(stmt, b, re.I), f"I16: verify-project-databases.sh contains {stmt}"


@pytest.mark.parametrize("needle,req", [
    ("has_table_privilege", "I16.1"), ("has_schema_privilege", "I16.1"), ("provision.template_migration", "I16.3"),
    ("project.system", "I16.3"), ("docker inspect", "I16.4"), ("max_connections", "I16.7"), ("PgBouncer", "I16.7"),
    ("db_consistency", "I16.6"), ("--privileges", "I16.2"),
])
def test_i16_the_script_checks(needle, req):
    assert needle in body(), f"{req}: verify-project-databases.sh does not use {needle}"


def test_i16_4_container_dsns_are_never_printed():
    """I16.4, I18.7: values of DSN variables are reduced to their database part before any output."""
    b = body()
    for line in b.splitlines():
        if re.search(r"\b(echo|printf)\b", line):
            assert not re.search(r"\$\{?(\w*PASSWORD|\w*TOKEN|\w*SECRET|DATABASE_URL|\w*_DSN|\w*_URI)\}?", line), \
                f"I18.7: prints a secret or DSN: {line.strip()[:80]}"


def test_i16_5_the_functional_isolation_part_exists():
    """I16.5: two throwaway projects through the API; A's ids under B's pid are 404 on every module."""
    b = body()
    assert re.search(r"/projects", b) and "404" in b, "I16.5: no functional isolation part (two projects, 404s)"
    for module in ("qualification", "control-objectives", "controls", "engine", "report"):
        assert module in b, f"I16.5: the functional part does not cover {module}"


def test_i16_7_warns_naming_pgbouncer_without_failing():
    b = body()
    assert re.search(r"WARN[^\n]*PgBouncer", b), "I16.7: no WARN line naming PgBouncer"
    assert "0.8" in b or "80" in b, "I16.7: the 80% of max_connections threshold is missing"


def test_i19_1_verify_db_access_checks_project_database_grants():
    """I19.1: verify-db-access.sh checks the grants of I16.1 on a throwaway project instead of probes in the
    platform module schemas."""
    text = DB_ACCESS.read_text()
    assert "project_" in text, "I19.1: verify-db-access.sh does not look into a project database"
    assert "select count(*) from core.system" not in text, "I19.1: verify-db-access.sh still probes core.system"
    assert not re.search(r"qualification\.\w+|engine\.\w+", text.split("project_", 1)[0]), \
        "I19.1: verify-db-access.sh probes module schemas of platform"


# ── against the bed ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def bed():
    b = ib.build("verify")
    yield b
    b.stop()


def run(bed, *args):
    assert SCRIPT.exists(), "I16: scripts/verify-project-databases.sh missing"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGHOST="127.0.0.1", PGPORT=str(bed.port), PGUSER="aisc-postgres-user", PGPASSWORD=bed.t.password,
               PGDATABASE="platform", NO_COLOR="1", VERIFY_SKIP_CONTAINERS="1", VERIFY_SKIP_FUNCTIONAL="1")
    r = subprocess.run([str(SCRIPT), *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert bed.t.password not in r.stdout + r.stderr, "I18.7: the script printed the password"
    return r


@contextmanager
def planted(bed, db, sql, undo):
    r = bed.psql(db, sql)
    assert r.returncode == 0, r.stderr
    try:
        yield
    finally:
        bed.psql(db, undo)


ALL = ("templates", "project_system", "qualification", "control_objectives", "engine", "report_composer", "controls")


def test_i16_passes_on_a_good_layout(bed):
    bed.require(*ALL)
    r = run(bed)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-500:]


def test_i16_1_fails_on_a_planted_extra_reader_grant(bed):
    bed.require(*ALL)
    with planted(bed, DB_A, "GRANT SELECT ON engine.project_config TO report_ro",
                 "REVOKE SELECT ON engine.project_config FROM report_ro"):
        r = run(bed)
    assert r.returncode != 0, "I16.1: an extra grant to report_ro passed"
    assert "engine.project_config" in r.stdout, "I16.1: the failure does not name engine.project_config"


def test_i16_1_fails_on_a_module_role_reaching_another_module(bed):
    bed.require(*ALL)
    with planted(bed, DB_A, "GRANT USAGE ON SCHEMA engine TO qualification_rw",
                 "REVOKE USAGE ON SCHEMA engine FROM qualification_rw"):
        r = run(bed)
    assert r.returncode != 0 and "qualification_rw" in r.stdout, "I16.1: cross-module USAGE passed"


def test_i16_3_fails_on_a_missing_template_file(bed):
    bed.require(*ALL)
    with planted(bed, DB_A, "DELETE FROM provision.template_migration WHERE name = '0009_engine.sql'",
                 "INSERT INTO provision.template_migration (name) VALUES ('0009_engine.sql')"):
        r = run(bed)
    assert r.returncode != 0 and "0009_engine.sql" in r.stdout, "I16.3: a missing template file passed"


def test_i16_3_fails_on_a_project_without_its_database(bed):
    lost = "f0000000-0000-4000-8000-00000000000f"
    bed.require(*ALL)
    with planted(bed, "platform", f"INSERT INTO core.project (pid, name, slug) VALUES ('{lost}', 'Lost', 'lost')",
                 f"DELETE FROM core.project WHERE pid = '{lost}'"):
        r = run(bed)
    assert r.returncode != 0 and lost.replace("-", "") in r.stdout, "I16.3: a project without a database passed"


def test_i16_3_fails_on_a_module_behind_its_head(bed):
    bed.require(*ALL)
    name = bed.scalar(DB_A, "SELECT version_num FROM control_objectives.alembic_version")
    with planted(bed, DB_A, "DELETE FROM control_objectives.alembic_version",
                 f"INSERT INTO control_objectives.alembic_version VALUES ('{name}')"):
        r = run(bed)
    assert r.returncode != 0 and "control_objectives" in r.stdout, "I16.3: a module behind its head passed"


def test_i16_2_privileges_fail_while_a_shared_module_schema_is_reachable(bed):
    """I16.2: after C9 the retired schemas are unreachable by every non-superuser role. A module schema in
    `platform` that its role can still use makes `--privileges` fail and is named."""
    bed.require(*ALL)
    made = bed.scalar("platform", "SELECT to_regnamespace('qualification') IS NULL") == "t"
    setup = ("CREATE SCHEMA IF NOT EXISTS qualification AUTHORIZATION qualification_rw;"
             "GRANT USAGE ON SCHEMA qualification TO qualification_rw")
    undo = "DROP SCHEMA qualification CASCADE" if made else "SELECT 1"
    with planted(bed, "platform", setup, undo):
        r = run(bed, "--privileges")
    assert r.returncode != 0 and "qualification" in r.stdout, "I16.2: a reachable shared schema passed --privileges"


def test_i16_1_i1_4_fails_on_a_reader_privilege_in_platform_beyond_i1_4(bed):
    """I1.4, I16.1: in `platform` report_ro keeps only CONNECT, USAGE core, SELECT core.project; one more grant
    fails the privileges check and is named."""
    bed.require(*ALL)
    with planted(bed, "platform", "GRANT SELECT ON core.project_member TO report_ro",
                 "REVOKE SELECT ON core.project_member FROM report_ro"):
        r = run(bed, "--privileges")
    assert r.returncode != 0 and "core.project_member" in r.stdout, "I1.4: an extra platform grant to report_ro passed"


def test_i16_3_fails_on_a_duplicate_or_dangling_version(bed):
    """I16.3: project.system numbers are unique and positive, and every system_id of every module resolves in
    the same database: a card naming a pid absent from project.system fails and is named."""
    bed.require(*ALL)
    ghost = "8d8d8d8d-0000-4000-8000-00000000008d"
    sql = (f"SET session_replication_role = replica; INSERT INTO qualification.qualification (id, \"systemName\","
           f" \"systemVersion\", company, description, \"targetUseCase\", \"targetUsers\", updated_at, system_id)"
           f" VALUES ('iso-dangling', 'x', '', '', '', '', '', now(), '{ghost}')")
    with planted(bed, DB_A, sql, "SET session_replication_role = replica;"
                                 " DELETE FROM qualification.qualification WHERE id = 'iso-dangling'"):
        r = run(bed)
    assert r.returncode != 0 and ghost in r.stdout, "I16.3: a system_id that does not resolve passed"


def test_i16_7_i17_1_warns_naming_pgbouncer_when_the_budget_passes_80_percent(bed):
    """I16.7, I17.1: (projects x per-project budget of section 17) + base above 80% of max_connections (100)
    prints a WARN naming PgBouncer. Ten more core.project rows are planted (their missing databases also fail
    I16.3; this test reads only the WARN line)."""
    bed.require(*ALL)
    pids = [f"e{i:07d}-0000-4000-8000-0000000000e{i}" for i in range(10)]
    values = ", ".join(f"('{p}', 'Budget {i}', 'budget-{i}')" for i, p in enumerate(pids))
    with planted(bed, "platform", f"INSERT INTO core.project (pid, name, slug) VALUES {values}",
                 "DELETE FROM core.project WHERE slug LIKE 'budget-%'"):
        r = run(bed)
    assert re.search(r"WARN[^\n]*PgBouncer", r.stdout), "I16.7: no WARN naming PgBouncer at 12 projects"


def test_i16_7_no_budget_warning_for_two_projects(bed):
    bed.require(*ALL)
    r = run(bed)
    assert not re.search(r"WARN[^\n]*PgBouncer", r.stdout), "I16.7: WARN at two projects"
