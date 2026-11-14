"""The owner roles on an install made before them: nothing is lost and no service is locked out.

A throwaway bed is first set up as an install was before the owner roles: platform_rw migrates the platform
database (migrations before the owner role), makes the project databases and applies the template files
before the owner roles, and owns all of it; it may end other sessions, and the inspector reads all data.
Every module migrates and rows are written. Then the bed starts as the stack now starts: postgres-setup's
files (init/owner-roles.sql first, init/project-database-setup.sql last, in template1 and in each project
database), the platform's migrations as platform_migrator, its template top-up, and every module's migrate
command again. Each service's role must still do what it did; only what the owner roles take away is gone.

    cd scripts/tests && uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' \
        pytest -q -p no:cacheprovider test_owner_roles_on_an_existing_install.py
"""

from __future__ import annotations

import psycopg
import pytest

import isolation_bed as ib
from throwaway import Throwaway, platform_migration

ROOT = ib.ROOT
INIT = ROOT / "init"
#: the first template file and migration of the owner roles: an install made before has none of them
FIRST_TEMPLATE_WITH_OWNERS = "0033_owner_roles.sql"
FIRST_MIGRATION_WITH_OWNERS = "0015_owner_role.sql"
A, B = ib.A, ib.B
DB_A, DB_B = ib.project_db(A), ib.project_db(B)
V1 = "11111111-1111-4111-8111-111111111111"
V2 = "22222222-2222-4222-8222-222222222222"

#: what each project database holds before the upgrade, counted again after it
COUNTED = ("project.system", "evidence.link", "evidence.review", "trace.call", "ledger.platform_action")

OLD_PROVISION = """
import shutil, sys, tempfile
from pathlib import Path
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo
from platform_service import projectdb
from platform_service.migrate import migrate

dsn, first_new = sys.argv[1], sys.argv[2]
older = Path(tempfile.mkdtemp())
for f in sorted(projectdb.TEMPLATE.glob("*.sql")):
    if f.name < first_new:
        shutil.copy(f, older)
for pid in sys.argv[3:]:
    name = projectdb.database_name(pid)
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    with psycopg.connect(make_conninfo(dsn, dbname=name)) as conn:
        migrate(conn, older, projectdb.TRACKING_TABLE)
        projectdb.sync_platform_actions(conn)
"""

SEED = f"""
INSERT INTO project.system (pid, number, name, created_by) VALUES ('{V1}', 1, 'Card', 'alice'), ('{V2}', 2, 'Card', 'alice');
INSERT INTO evidence.link (objective_id, kind, item_key, created_by, system_id) VALUES ('O1', 'test', 'pkg', 'alice', '{V1}');
INSERT INTO evidence.review (system_id, reviewed_by, reviewed_by_name) VALUES ('{V1}', 'bob', 'Bob');
INSERT INTO trace.call (run, seq, connection, door, started_at, ended_at, request, outcome, hash)
VALUES ('pass:{'a' * 64}', 1, 'sut', 'openai', now(), now(), '{{}}', 'answered', '{'b' * 64}');
"""


def _must(bed, db, sql, role=None) -> None:
    r = bed.psql(db, sql, role=role)
    assert r.returncode == 0, f"{db} as {role or 'the superuser'}: " + ib._redact(bed, r.stderr.strip()[-400:])


def _counts(bed) -> dict:
    out = {}
    for db in (DB_A, DB_B):
        for rel in COUNTED:
            out[(db, rel)] = bed.scalar(db, f"SELECT count(*) FROM {rel}")
    out[("platform", "core.project_member")] = bed.scalar("platform", "SELECT count(*) FROM core.project_member")
    out[("platform", "ledger.state")] = bed.scalar("platform", "SELECT count(*) FROM ledger.state")
    return out


def _upgrade(bed) -> None:
    """The start of the new stack: postgres-setup's order, then the platform, then every module."""
    for f in ("project-databases", "owner-roles", "report-roles", "inspector-role", "platform-role"):
        ib._su_file(bed, "platform", INIT / f"{f}.sql", f"upgrade-{f}")
    for db in ("template1", DB_A, DB_B):
        ib._su_file(bed, db, INIT / "project-database-setup.sql", f"upgrade-setup-{db}")
    for m in sorted((ROOT / "platform/migrations").glob("*.sql")):
        if m.name >= FIRST_MIGRATION_WITH_OWNERS:
            platform_migration(bed.t, m)
    ib.provision(bed, [A, B])
    ib.migrate_modules(bed)


@pytest.fixture(scope="module")
def bed():
    t = Throwaway.start("iso-top-upgrade")
    b = ib.IsoBed(t)
    try:
        # the install as it was
        ib._su_file(b, "postgres", INIT / "platform-db.sql", "init")
        for f in ("project-databases", "inspector-role", "report-roles", "platform-role"):
            ib._su_file(b, "platform", INIT / f"{f}.sql", f"init-{f}")
        _must(b, "platform", "GRANT pg_signal_backend TO platform_rw; GRANT pg_read_all_data TO inspector_ro;"
                             " GRANT CONNECT, TEMPORARY ON DATABASE platform TO PUBLIC;")
        for m in sorted((ROOT / "platform/migrations").glob("*.sql")):
            if m.name < FIRST_MIGRATION_WITH_OWNERS:
                platform_migration(t, m)
        for pid in (A, B):
            _must(b, "platform", f"INSERT INTO core.project (pid, name, slug) VALUES ('{pid}', 'Up {pid[:1]}',"
                                 f" 'up-{pid[:8]}')", role="platform_rw")
            _must(b, "platform", "INSERT INTO core.project_member (project_id, subject, role)"
                                 f" VALUES ('{pid}', 'alice', 'owner')", role="platform_rw")
        ib._run(b, "old-provision", ["uv", "run", "--quiet", "--extra", "dev", "python", "-c", OLD_PROVISION,
                                     b.dsn("platform_rw", "platform"), FIRST_TEMPLATE_WITH_OWNERS, A, B],
                ROOT / "platform", {}, "provision as before the owner roles")
        b.projects += [A, B]
        ib.migrate_modules(b)
        for db in (DB_A, DB_B):
            _must(b, db, SEED, role="platform_rw")
        _must(b, "platform", "INSERT INTO ledger.state (db, tx_id, tx_hash) VALUES"
                             f" ('ledger{'c' * 32}', 7, '\\x{'d' * 64}')", role="platform_rw")
        b.require(*b.problems)                                       # the old install itself must build
        assert b.scalar(DB_A, "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()") \
            == "platform_rw"
        b.before = _counts(b)
        _upgrade(b)
        yield b
    finally:
        t.stop()


def test_the_upgrade_runs_without_a_problem(bed):
    assert bed.problems == {}


def test_nothing_is_lost(bed):
    assert _counts(bed) == bed.before


def test_the_verified_ledger_state_moves_to_the_log(bed):
    assert bed.scalar("platform", "SELECT tx_id FROM ledger.state_log WHERE db = 'ledger" + "c" * 32 + "'") == "7"


def test_what_platform_rw_owned_now_belongs_to_platform_owner(bed):
    for db in (DB_A, DB_B):
        assert bed.scalar(db, "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()") \
            == "platform_owner"
        assert bed.scalar(db, "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                              " WHERE pg_get_userbyid(c.relowner) = 'platform_rw' AND n.nspname <> 'catalogue'") == "0"
        for schema in ib.MODULES:
            assert bed.scalar(db, f"SELECT pg_get_userbyid(nspowner) FROM pg_namespace WHERE nspname = '{schema}'") \
                == f"{schema}_owner"
    assert bed.scalar("platform", "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
                                  " WHERE pg_get_userbyid(c.relowner) = 'platform_rw'"
                                  " AND n.nspname IN ('core', 'ledger')") == "0"


def _as(bed, db, role, sql) -> str:
    r = bed.psql(db, sql, role=role)
    return ib._redact(bed, r.stderr.strip()) if r.returncode else ""


def test_platform_rw_still_reads_and_writes_the_platform_database(bed):
    assert _as(bed, "platform", "platform_rw", f"""
        BEGIN;
        INSERT INTO core.project_member (project_id, subject, role) VALUES ('{A}', 'carol', 'viewer');
        UPDATE core.project_member SET role = 'editor' WHERE subject = 'carol';
        DELETE FROM core.project_member WHERE subject = 'carol';
        UPDATE core.project SET description = 'kept' WHERE pid = '{A}';
        SELECT count(*) FROM ledger.pool; SELECT count(*) FROM ledger.state_log; SELECT count(*) FROM core.outbox;
        ROLLBACK;""") == ""


def test_platform_rw_still_reads_and_writes_a_project_database(bed):
    assert _as(bed, DB_A, "platform_rw", f"""
        BEGIN;
        INSERT INTO project.system (number, name, created_by) VALUES (3, 'Card', 'alice');
        UPDATE project.system SET description = 'corrected' WHERE number = 3;
        INSERT INTO evidence.link (objective_id, kind, item_key, created_by, system_id)
             VALUES ('O2', 'test', 'pkg', 'alice', '{V2}');
        DELETE FROM evidence.link WHERE objective_id = 'O2';
        INSERT INTO trace.call (run, seq, connection, door, started_at, ended_at, request, outcome, hash)
             VALUES ('pass:{'a' * 64}', 2, 'sut', 'openai', now(), now(), '{{}}', 'answered', '{'e' * 64}');
        SELECT count(*) FROM connection.endpoint; SELECT count(*) FROM llm.provider;
        SELECT count(id) FROM engine.aisc_backend_ledgeroutbox;
        CREATE SCHEMA catalogue; CREATE TABLE catalogue.mode (mode text);
        ROLLBACK;""") == ""


def test_platform_rw_lost_only_what_the_guards_need(bed):
    assert "permission denied" in _as(bed, DB_A, "platform_rw", f"DELETE FROM project.system WHERE pid = '{V1}'")
    assert "must be owner" in _as(bed, DB_A, "platform_rw", "ALTER TABLE trace.call DISABLE TRIGGER call_append_only")
    assert "permission denied" in _as(bed, "platform", "platform_rw", f"CREATE DATABASE project_{'f' * 32}")


@pytest.mark.parametrize("schema,role", sorted(ib.MODULES.items()))
def test_each_module_role_still_works_in_its_schema(bed, schema, role):
    tracker = ib.TRACKERS[schema]
    assert _as(bed, DB_A, role, f"""
        BEGIN;
        SELECT count(*) FROM {tracker};
        SELECT count(*) FROM project.system;
        CREATE TABLE {schema}.upgrade_probe (id int); INSERT INTO {schema}.upgrade_probe VALUES (1);
        DROP TABLE {schema}.upgrade_probe;
        ROLLBACK;""") == ""


@pytest.mark.parametrize("role", ["report_ro", "dashboard_ro"])
def test_the_readers_still_read(bed, role):
    assert _as(bed, DB_A, role, "SELECT count(*) FROM project.system; SELECT count(*) FROM evidence.link;") == ""


def test_the_inspector_reads_by_schema(bed):
    assert _as(bed, DB_A, "inspector_ro", "SELECT count(*) FROM trace.call; SELECT count(*) FROM project.system;"
                                          " SELECT count(*) FROM engine.django_migrations;") == ""
    assert "permission denied" in _as(bed, DB_A, "inspector_ro", "SELECT count(*) FROM connection.endpoint")
    assert _as(bed, "platform", "inspector_ro", "SELECT count(*) FROM core.project_member;"
                                                " SELECT count(*) FROM ledger.state_log;") == ""


def test_card_versions_are_kept_and_evidence_restricts(bed):
    assert "is kept" in _as(bed, DB_A, None, f"DELETE FROM project.system WHERE pid = '{V1}'")
    assert bed.scalar(DB_A, "SELECT string_agg(DISTINCT confdeltype::text, '') FROM pg_constraint"
                            " WHERE confrelid = 'project.system'::regclass"
                            " AND conrelid::regclass::text LIKE 'evidence.%'") == "r"


def test_the_platform_drops_a_project_database_an_app_still_holds(bed):
    held = psycopg.connect(bed.dsn("engine_rw", DB_B), autocommit=True)
    try:
        r = bed.psql("platform", f"""
            ALTER DATABASE {DB_B} ALLOW_CONNECTIONS false;
            SELECT aisc_setup.end_project_sessions('{DB_B}');
            DROP DATABASE {DB_B};""", role="platform_migrator")
        assert r.returncode == 0, ib._redact(bed, r.stderr)
        assert bed.scalar("platform", f"SELECT count(*) FROM pg_database WHERE datname = '{DB_B}'") == "0"
    finally:
        held.close()
