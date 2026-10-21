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
    assert SCRIPT.exists(), "scripts/verify-project-databases.sh missing"
    return "\n".join(line for line in SCRIPT.read_text().splitlines() if not line.lstrip().startswith("#"))


# static


def test_verify_sh_runs_it():
    stack = re.search(r"for s in ([^;]+); do", VERIFY.read_text()).group(1).split()
    assert "verify-project-databases.sh" in stack, f"verify.sh does not run verify-project-databases.sh: {stack}"


def test_the_script_is_read_only():
    """Read-only sessions and no statement that changes anything."""
    b = body()
    assert "default_transaction_read_only" in b, "the script's sessions are not read-only"
    for stmt in (r"\bGRANT\b", r"\bREVOKE\b", r"\bALTER\s+(TABLE|ROLE|SCHEMA|DATABASE)\b", r"\bDROP\s",
                 r"\bTRUNCATE\b", r"\bDELETE\s+FROM\b", r"\bINSERT\s+INTO\b", r"\bUPDATE\s+\w+\s+SET\b"):
        assert not re.search(stmt, b, re.I), f"verify-project-databases.sh contains {stmt}"


def test_containers_check_never_prints_a_dsn():
    """Values of DSN variables are reduced to their database part before any output."""
    b = body()
    for line in b.splitlines():
        if re.search(r"\b(echo|printf)\b", line):
            assert not re.search(r"\$\{?(\w*PASSWORD|\w*TOKEN|\w*SECRET|DATABASE_URL|\w*_DSN|\w*_URI)\}?", line), \
                f"prints a secret or DSN: {line.strip()[:80]}"


def test_the_functional_isolation_part_exists():
    """Two throwaway projects through the API; A's ids under B's pid are 404 on every module."""
    b = body()
    assert re.search(r"/projects", b) and "404" in b, "isolation: no functional part (two projects, 404s)"
    for module in ("qualification", "control-objectives", "controls", "engine", "report"):
        assert module in b, f"isolation: the functional part does not cover {module}"


def test_verify_db_access_checks_project_database_grants():
    """verify-db-access.sh checks the module grants on a throwaway project, not by probing module schemas
    in platform."""
    text = DB_ACCESS.read_text()
    assert "project_" in text, "verify-db-access.sh does not look into a project database"
    assert "select count(*) from core.system" not in text, "verify-db-access.sh still probes core.system"
    assert not re.search(r"qualification\.\w+|engine\.\w+", text.split("project_", 1)[0]), \
        "verify-db-access.sh probes module schemas of platform"


# against the bed


@pytest.fixture(scope="module")
def bed():
    b = ib.build("verify")
    yield b
    b.stop()


def run(bed, *args):
    assert SCRIPT.exists(), "scripts/verify-project-databases.sh missing"
    env = {k: v for k, v in os.environ.items() if not k.startswith("PG")}
    env.update(PGHOST="127.0.0.1", PGPORT=str(bed.port), PGUSER="aisc-postgres-user", PGPASSWORD=bed.t.password,
               PGDATABASE="platform", NO_COLOR="1", VERIFY_SKIP_CONTAINERS="1", VERIFY_SKIP_FUNCTIONAL="1")
    r = subprocess.run([str(SCRIPT), *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)
    assert bed.t.password not in r.stdout + r.stderr, "the script printed the password"
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


def test_every_check_passes_on_a_good_layout(bed):
    bed.require(*ALL)
    r = run(bed)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-500:]


def test_privileges_fail_on_a_planted_extra_reader_grant(bed):
    bed.require(*ALL)
    with planted(bed, DB_A, "GRANT SELECT ON engine.aisc_backend_projectconfig TO report_ro",
                 "REVOKE SELECT ON engine.aisc_backend_projectconfig FROM report_ro"):
        r = run(bed)
    assert r.returncode != 0, "privileges: an extra grant to report_ro passed"
    assert "engine.aisc_backend_projectconfig" in r.stdout, "privileges: the failure does not name engine.aisc_backend_projectconfig"


def test_privileges_fail_on_a_module_role_reaching_another_module(bed):
    bed.require(*ALL)
    with planted(bed, DB_A, "GRANT USAGE ON SCHEMA engine TO qualification_rw",
                 "REVOKE USAGE ON SCHEMA engine FROM qualification_rw"):
        r = run(bed)
    assert r.returncode != 0 and "qualification_rw" in r.stdout, "privileges: cross-module USAGE passed"


def test_databases_fail_on_a_missing_template_file(bed):
    bed.require(*ALL)
    with planted(bed, DB_A, "DELETE FROM provision.template_migration WHERE name = '0009_engine.sql'",
                 "INSERT INTO provision.template_migration (name) VALUES ('0009_engine.sql')"):
        r = run(bed)
    assert r.returncode != 0 and "0009_engine.sql" in r.stdout, "databases: a missing template file passed"


def test_databases_fail_on_a_project_without_its_database(bed):
    lost = "f0000000-0000-4000-8000-00000000000f"
    bed.require(*ALL)
    with planted(bed, "platform", f"INSERT INTO core.project (pid, name, slug) VALUES ('{lost}', 'Lost', 'lost')",
                 f"DELETE FROM core.project WHERE pid = '{lost}'"):
        r = run(bed)
    assert r.returncode != 0 and lost.replace("-", "") in r.stdout, "databases: a project without a database passed"


def test_databases_fail_on_a_module_behind_its_head(bed):
    bed.require(*ALL)
    name = bed.scalar(DB_A, "SELECT version_num FROM control_objectives.alembic_version")
    with planted(bed, DB_A, "DELETE FROM control_objectives.alembic_version",
                 f"INSERT INTO control_objectives.alembic_version VALUES ('{name}')"):
        r = run(bed)
    assert r.returncode != 0 and "control_objectives" in r.stdout, "databases: a module behind its head passed"


def test_placement_fails_with_privileges_while_a_shared_module_schema_is_reachable(bed):
    """The retired shared schemas must be unreachable by every non-superuser role. A module schema in
    `platform` that its role can still use makes `--privileges` fail and is named."""
    bed.require(*ALL)
    made = bed.scalar("platform", "SELECT to_regnamespace('qualification') IS NULL") == "t"
    setup = ("CREATE SCHEMA IF NOT EXISTS qualification AUTHORIZATION qualification_rw;"
             "GRANT USAGE ON SCHEMA qualification TO qualification_rw")
    undo = "DROP SCHEMA qualification CASCADE" if made else "SELECT 1"
    with planted(bed, "platform", setup, undo):
        r = run(bed, "--privileges")
    assert r.returncode != 0 and "qualification" in r.stdout, "placement: a reachable shared schema passed --privileges"


def test_privileges_fail_on_a_reader_privilege_in_platform_beyond_its_list(bed):
    """In `platform` report_ro keeps only CONNECT, USAGE core, SELECT core.project; one more grant fails the
    privileges check and is named."""
    bed.require(*ALL)
    with planted(bed, "platform", "GRANT SELECT ON core.project_member TO report_ro",
                 "REVOKE SELECT ON core.project_member FROM report_ro"):
        r = run(bed, "--privileges")
    assert r.returncode != 0 and "core.project_member" in r.stdout, "privileges: an extra platform grant to report_ro passed"


def test_databases_fail_on_a_duplicate_or_dangling_version(bed):
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
    assert r.returncode != 0 and ghost in r.stdout, "databases: a system_id that does not resolve passed"


def test_connections_warn_naming_pgbouncer_when_the_budget_passes_80_percent(bed):
    """(projects x per-project connection budget) + base above 80% of max_connections (100) prints a WARN
    naming PgBouncer. Ten more core.project rows are planted (their missing databases also fail the
    completeness check; this test reads only the WARN line)."""
    bed.require(*ALL)
    pids = [f"e{i:07d}-0000-4000-8000-0000000000e{i}" for i in range(10)]
    values = ", ".join(f"('{p}', 'Budget {i}', 'budget-{i}')" for i, p in enumerate(pids))
    with planted(bed, "platform", f"INSERT INTO core.project (pid, name, slug) VALUES {values}",
                 "DELETE FROM core.project WHERE slug LIKE 'budget-%'"):
        r = run(bed)
    assert re.search(r"WARN[^\n]*PgBouncer", r.stdout), "connections: no WARN naming PgBouncer at 12 projects"


def test_connections_no_budget_warning_for_two_projects(bed):
    bed.require(*ALL)
    r = run(bed)
    assert not re.search(r"WARN[^\n]*PgBouncer", r.stdout), "connections: WARN at two projects"


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


def test_privileges_reader_list_is_what_the_control_objectives_migrations_grant():
    """The readers may read exactly the tables the migrations grant them; a migration that grants a new
    table to the readers must add it to READER_TABLES too, or the stack's check fails on a good install."""
    assert set(_verify_reader_tables()["control_objectives"]) == _control_objectives_reader_grants()


def test_isolation_signs_in_through_the_gateway_as_a_person_does():
    """The functional check runs after the README's own steps. The gateway takes its own session, never a
    bearer token alone, so the check signs in at the launcher's sign-in form with the development account
    (VERIFY_USER / VERIFY_PASSWORD, default user / user) and keeps the session's cookies, as verify-sso.sh
    does; the platform API is the launcher's (VERIFY_BASE_URL), the modules' APIs are on VERIFY_APPS_URL."""
    text = (ROOT / "scripts/verify-project-databases.sh").read_text()
    for needle in ("VERIFY_USER", "VERIFY_PASSWORD", "VERIFY_APPS_URL", "HTTPCookieProcessor", "def _signed_in"):
        assert needle in text, needle
    body = text[text.index("def isolation_functional"):]
    assert "_signed_in()" in body and "VERIFY_ACCESS_TOKEN" not in body


UNOPENED = "c0000000-0000-4000-8000-0000000000c3"


def test_databases_pass_with_a_warning_on_a_project_no_module_has_opened_yet(bed):
    """Each module migrates a project's database the first time it opens it, so a project just created (its
    template applied, every module schema empty) is not a failure; a module schema with tables but no
    history is."""
    bed.require(*ALL)
    db = ib.project_db(UNOPENED)
    try:
        ib.provision(bed, [UNOPENED])
        r = run(bed)
        mine = [line for line in r.stdout.splitlines() if db in line]
        assert not [line for line in mine if "FAIL" in line], "\n".join(mine)
        assert any("WARN" in line and "has not opened this project yet" in line for line in mine), "\n".join(mine)
        bed.psql(db, "CREATE TABLE report_composer.stray (x int)")
        r = run(bed)
        assert any("FAIL" in line and db in line and "report_composer" in line for line in r.stdout.splitlines())
    finally:
        bed.psql("postgres", f'DROP DATABASE IF EXISTS "{db}" WITH (FORCE)')
        bed.psql("platform", f"DELETE FROM core.project WHERE pid = '{UNOPENED}'")


def test_isolation_reuses_its_two_projects():
    """A project keeps its ledger database for good, deleted or not: two projects made per run would use up
    the pool. The check finds its two by name and makes them only the first time."""
    b = body()
    assert '"verify isolation A"' in b and '"verify isolation B"' in b
    assert '"DELETE", f"/api/projects/' not in b


def test_isolation_tags_what_it_adds_to_a_reused_project():
    """A name the previous run already used is refused (a layout's name is unique in its project)."""
    b = body()
    assert '"version": tag' in b and 'f"verify {tag}"' in b


def test_the_consistency_check_runs_before_the_functional_part_makes_projects():
    """The isolation check makes (or reuses) its two projects and opens them in every module, which migrates
    them then; the consistency check reading those databases at the same moment saw a table halfway through
    its migrations (its references check, C4, could not run)."""
    main = (ROOT / "scripts/verify-project-databases.sh").read_text().split("def main():", 1)[1]
    assert main.index("consistency()") < main.index("isolation_functional()")
