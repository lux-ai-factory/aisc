"""scripts/verify-project-databases.sh, the check that every project's database is complete and isolated.

Static checks on the script, then runs against the isolation bed (two throwaway project databases, every
module migrated, never the host's 5432). The script reads its cluster from the PG* environment (like
scripts/verify-db-consistency.sh), so a test points it at the throwaway; the container part (docker
inspect) and the functional API part are switched off here with VERIFY_SKIP_CONTAINERS=1 and
VERIFY_SKIP_FUNCTIONAL=1 and checked statically.
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


# static


def test_i16_the_script_exists_and_is_executable():
    assert SCRIPT.exists(), "I16: scripts/verify-project-databases.sh missing"
    assert os.access(SCRIPT, os.X_OK), "I16: verify-project-databases.sh is not executable"


def test_i19_1_verify_sh_runs_it_instead_of_verify_one_database():
    text = VERIFY.read_text()
    assert "verify-project-databases.sh" in text, "I19.1: verify.sh does not run verify-project-databases.sh"
    assert "verify-one-database.sh" not in text, "I19.1: verify.sh still runs verify-one-database.sh"


def test_i16_the_script_is_read_only():
    """Read-only sessions and no statement that changes anything."""
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
    """Values of DSN variables are reduced to their database part before any output."""
    b = body()
    for line in b.splitlines():
        if re.search(r"\b(echo|printf)\b", line):
            assert not re.search(r"\$\{?(\w*PASSWORD|\w*TOKEN|\w*SECRET|DATABASE_URL|\w*_DSN|\w*_URI)\}?", line), \
                f"I18.7: prints a secret or DSN: {line.strip()[:80]}"


def test_i16_5_the_functional_isolation_part_exists():
    """Two throwaway projects through the API; A's ids under B's pid are 404 on every module."""
    b = body()
    assert re.search(r"/projects", b) and "404" in b, "I16.5: no functional isolation part (two projects, 404s)"
    for module in ("qualification", "control-objectives", "controls", "engine", "report"):
        assert module in b, f"I16.5: the functional part does not cover {module}"


def test_i16_7_warns_naming_pgbouncer_without_failing():
    b = body()
    assert re.search(r"WARN[^\n]*PgBouncer", b), "I16.7: no WARN line naming PgBouncer"
    assert "0.8" in b or "80" in b, "I16.7: the 80% of max_connections threshold is missing"


def test_i19_1_verify_db_access_checks_project_database_grants():
    """verify-db-access.sh checks the module grants on a throwaway project, not by probing module schemas
    in platform."""
    text = DB_ACCESS.read_text()
    assert "project_" in text, "I19.1: verify-db-access.sh does not look into a project database"
    assert "select count(*) from core.system" not in text, "I19.1: verify-db-access.sh still probes core.system"
    assert not re.search(r"qualification\.\w+|engine\.\w+", text.split("project_", 1)[0]), \
        "I19.1: verify-db-access.sh probes module schemas of platform"


# against the bed


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
    with planted(bed, DB_A, "GRANT SELECT ON engine.aisc_backend_projectconfig TO report_ro",
                 "REVOKE SELECT ON engine.aisc_backend_projectconfig FROM report_ro"):
        r = run(bed)
    assert r.returncode != 0, "I16.1: an extra grant to report_ro passed"
    assert "engine.aisc_backend_projectconfig" in r.stdout, "I16.1: the failure does not name engine.aisc_backend_projectconfig"


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
    """The retired shared schemas must be unreachable by every non-superuser role. A module schema in
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
    """In `platform` report_ro keeps only CONNECT, USAGE core, SELECT core.project; one more grant fails the
    privileges check and is named."""
    bed.require(*ALL)
    with planted(bed, "platform", "GRANT SELECT ON core.project_member TO report_ro",
                 "REVOKE SELECT ON core.project_member FROM report_ro"):
        r = run(bed, "--privileges")
    assert r.returncode != 0 and "core.project_member" in r.stdout, "I1.4: an extra platform grant to report_ro passed"


def test_i16_3_fails_on_a_duplicate_or_dangling_version(bed):
    """project.system numbers are unique and positive, and every system_id of every module resolves in
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
    """(projects x per-project connection budget) + base above 80% of max_connections (100) prints a WARN
    naming PgBouncer. Ten more core.project rows are planted (their missing databases also fail the
    completeness check; this test reads only the WARN line)."""
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


def _verify_reader_tables() -> dict:
    """READER_TABLES as verify-project-databases.sh declares it."""
    import ast

    text = (ROOT / "scripts/verify-project-databases.sh").read_text()
    start = text.index("READER_TABLES = {")
    end = text.index("\n}", start) + 2
    return ast.literal_eval(text[start + len("READER_TABLES = "):end])


def _control_objectives_reader_grants() -> set[str]:
    """Every control_objectives table its alembic migrations grant to the readers."""
    import ast

    granted = set()
    for path in sorted((ROOT / "apps/control-objectives/alembic/versions").glob("*.py")):
        tree = ast.parse(path.read_text())
        values = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                try:
                    values[node.targets[0].id] = ast.literal_eval(node.value)
                except ValueError:
                    if isinstance(node.value, ast.Dict):           # {"report_ro": READ, ...}
                        values[node.targets[0].id] = {
                            ast.literal_eval(k): values.get(v.id, ()) if isinstance(v, ast.Name) else ast.literal_eval(v)
                            for k, v in zip(node.value.keys, node.value.values)}
        granted |= set(values.get("READER_TABLES", ()))
        for tables in (values.get("GRANTS") or {}).values():
            granted |= set(tables)
    return granted


def test_i16_1_the_reader_list_is_what_the_control_objectives_migrations_grant():
    """The readers may read exactly the tables the migrations grant them; a migration that grants a new
    table to the readers must add it to READER_TABLES too, or the stack's check fails on a good install."""
    assert set(_verify_reader_tables()["control_objectives"]) == _control_objectives_reader_grants()


def test_i16_5_signs_in_through_the_gateway_as_a_person_does():
    """The functional check runs after the README's own steps. The gateway takes its own session, never a
    bearer token alone, so the check signs in at the launcher's sign-in form with the development account
    (VERIFY_USER / VERIFY_PASSWORD, default user / user) and keeps the session's cookies, as verify-sso.sh
    does; the platform API is the launcher's (VERIFY_BASE_URL), the modules' APIs are on VERIFY_APPS_URL."""
    text = (ROOT / "scripts/verify-project-databases.sh").read_text()
    for needle in ("VERIFY_USER", "VERIFY_PASSWORD", "VERIFY_APPS_URL", "HTTPCookieProcessor", "def _signed_in"):
        assert needle in text, needle
    body = text[text.index("def i16_5"):]
    assert "_signed_in()" in body and "VERIFY_ACCESS_TOKEN" not in body


def test_i16_5_takes_its_throwaway_projects_away_as_an_admin():
    """Only an admin deletes a project, typing its name: the check's cleanup signs in as the development
    admin (VERIFY_ADMIN_USER / VERIFY_ADMIN_PASSWORD, default admin / admin) and confirms with the name."""
    text = (ROOT / "scripts/verify-project-databases.sh").read_text()
    body = text[text.index("def i16_5"):text.index("# I16.6 and I16.7")]
    assert "VERIFY_ADMIN_USER" in text and "VERIFY_ADMIN_PASSWORD" in text
    assert '"confirm_name"' in body


UNOPENED = "c0000000-0000-4000-8000-0000000000c3"


def test_i16_3_a_project_no_module_has_opened_yet_passes_with_a_warning(bed):
    """Each module migrates a project's database the first time it opens it, so a project just created (its
    template applied, every module schema empty) is not a failure; a module schema with tables but no
    history is."""
    bed.require(*ALL)
    db = ib.project_db(UNOPENED)
    try:
        ib.provision(bed, [UNOPENED])
        r = run(bed)
        mine = [l for l in r.stdout.splitlines() if db in l]
        assert not [l for l in mine if "FAIL" in l], "\n".join(mine)
        assert any("WARN" in l and "has not opened this project yet" in l for l in mine), "\n".join(mine)
        bed.psql(db, "CREATE TABLE report_composer.stray (x int)")
        r = run(bed)
        assert any("FAIL" in l and db in l and "report_composer" in l for l in r.stdout.splitlines())
    finally:
        bed.psql("postgres", f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        bed.psql("platform", f"DELETE FROM core.project WHERE pid = '{UNOPENED}'")
