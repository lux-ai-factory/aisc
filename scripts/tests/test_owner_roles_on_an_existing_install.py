"""The owner roles on an install made before them: nothing is lost and no service is locked out.

A throwaway bed is first set up as an install was before the owner roles: platform_rw migrates the platform
database (migrations before the owner role), makes the project databases and applies the template files
before the owner roles, and owns all of it; it may end other sessions, and the inspector reads all data.
Every module migrates as its runtime role, with its code as it was before its own owner-role migration
(each module's tree at the commit before that migration was added, run with this checkout's environments),
and rows are written. Then the bed starts as the stack now starts: postgres-setup's files
(init/owner-roles.sql first, init/project-database-setup.sql last, in template1 and in each project
database), the platform's migrations as platform_migrator, its template top-up, and every module's migrate
command again, now as its migrator. Each service's role must still do what it did; only what the owner roles
take away is gone: the module roles read and write rows of tables that now belong to the module owners.

    cd scripts/tests && uv run --no-project --with pytest --with pyyaml --with 'psycopg[binary]' \
        pytest -q -p no:cacheprovider test_owner_roles_on_an_existing_install.py
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

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

#: each module's migration that hands its tables to its owner role: the install before had none of them
OWNER_ROLE_MIGRATIONS = {
    "qualification": "prisma/migrations/20261115000000_owner_role/migration.sql",
    "controls": "prisma/migrations/20261115000000_owner_role/migration.sql",
    "control-objectives": "alembic/versions/20261115000000_owner_role.py",
    "backend": "aisc_backend/migrations/0028_owner_role.py",
    "report-composer": "migrations/project/0008_owner_role.sql",
}
#: each module's environment, linked into the older tree
ENVIRONMENTS = ("node_modules", ".venv")
#: the migration trackers, which the upgrade adds a row to
TRACKER_TABLES = {"_prisma_migrations", "alembic_version", "django_migrations", "schema_migration"}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def modules_before_their_owner_roles(dest: Path) -> Path:
    """dest/apps/<module>: each module's tree at the commit before its owner-role migration was added (the
    working tree without that file while it is not committed yet), with this checkout's environments."""
    for module, migration in OWNER_ROLE_MIGRATIONS.items():
        here = ROOT / "apps" / module
        submodule = (here / ".git").exists()
        repo, path = (here, migration) if submodule else (ROOT, f"apps/{module}/{migration}")
        added = _git(repo, "log", "--diff-filter=A", "--format=%H", "-1", "--", path).strip()
        target = dest / "apps" / module
        target.mkdir(parents=True)
        tree = subprocess.run(["git", "-C", str(repo), "archive", f"{added}^" if added else "HEAD",
                               *([] if submodule else [f"apps/{module}"])], capture_output=True, check=True).stdout
        subprocess.run(["tar", "-x", "-C", str(target if submodule else dest)], input=tree, check=True)
        if not added:
            (target / migration).unlink(missing_ok=True)
        for env in ENVIRONMENTS:
            if (here / env).exists() and not (target / env).exists():
                (target / env).symlink_to(here / env)
    return dest


def _module_rows(bed) -> dict:
    """Rows of every module table but the migration trackers, per project database."""
    out = {}
    for db in (DB_A, DB_B):
        tables = bed.rows(db, "SELECT schemaname || '.' || tablename AS rel FROM pg_tables WHERE schemaname IN"
                              " ('qualification', 'controls', 'control_objectives', 'engine', 'report_composer')"
                              " ORDER BY 1")
        for row in tables:
            if row["rel"].split(".", 1)[1] not in TRACKER_TABLES:
                out[(db, row["rel"])] = bed.scalar(db, f"SELECT count(*) FROM {row['rel']}")
    return out

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

CARD = "c" + "0" * 31
#: a row of each module that names a card version, written as each module's runtime role before the upgrade
MODULE_SEED = {
    "qualification_rw": f"""
        INSERT INTO qualification.qualification (id, "systemName", "systemVersion", company, description,
               "targetUseCase", "targetUsers", updated_at, system_id)
        VALUES ('{CARD}', 'Card', '1', 'c', 'd', 'u', 'p', now(), '{V2}');""",
    "controls_rw": f"""
        INSERT INTO controls.source (id, slug, name, updated_at) VALUES ('s1', 's1', 'S1', now());
        INSERT INTO controls.checklist (id, title, "sourceId", "controlTopic", updated_at)
             VALUES ('c1', 'C1', 's1', 'T', now());
        INSERT INTO controls.checklist_question (id, "checklistId", "order", text, article, category)
             VALUES ('q1', 'c1', 1, 'Q?', 'Art. 1', 'Cat');
        INSERT INTO controls.submission (id, "checklistId", label, status, updated_at)
             VALUES ('sub1', 'c1', 'first', 'Draft', now());
        INSERT INTO controls.submission_answer (id, "submissionId", "questionId", answer, system_version_pid)
             VALUES ('a1', 'sub1', 'q1', 'Yes', '{V1}');""",
    "control_objectives_rw": f"""
        INSERT INTO control_objectives.project (id, name, objectives_digest, created_at, updated_at, system_id)
             VALUES ('a1', 'Card', '', now(), now(), '{V1}');""",
    "report_composer_rw": """
        INSERT INTO report_composer.layout (name, created_by, updated_by) VALUES ('Kept layout', 'alice', 'alice');""",
}

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
        before = modules_before_their_owner_roles(Path(tempfile.mkdtemp(prefix="modules-before-")))
        ib.migrate_modules(b, before)
        for db in (DB_A, DB_B):
            _must(b, db, SEED, role="platform_rw")
            for role, sql in MODULE_SEED.items():
                _must(b, db, sql, role=role)
        _must(b, "platform", "INSERT INTO ledger.state (db, tx_id, tx_hash) VALUES"
                             f" ('ledger{'c' * 32}', 7, '\\x{'d' * 64}')", role="platform_rw")
        b.require(*b.problems)                                       # the old install itself must build
        assert b.scalar(DB_A, "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = current_database()") \
            == "platform_rw"
        b.before = _counts(b)
        b.module_rows_before = _module_rows(b)
        assert b.scalar(DB_A, "SELECT tableowner FROM pg_tables WHERE schemaname = 'qualification'"
                              " AND tablename = 'qualification'") == "qualification_rw", "the old install"
        _upgrade(b)
        yield b
    finally:
        t.stop()


def test_the_upgrade_runs_without_a_problem(bed):
    assert bed.problems == {}


def test_nothing_is_lost(bed):
    assert _counts(bed) == bed.before


def test_no_module_row_is_lost(bed):
    assert bed.module_rows_before and _module_rows(bed) == bed.module_rows_before


@pytest.mark.parametrize("schema", sorted(ib.MODULES))
def test_every_module_table_now_belongs_to_its_owner_role(bed, schema):
    for db in (DB_A, DB_B):
        owners = {r["tableowner"] for r in bed.rows(db, "SELECT DISTINCT tableowner FROM pg_tables"
                                                        f" WHERE schemaname = '{schema}'")}
        assert owners == {f"{schema}_owner"}, (db, owners)


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


#: what each module's runtime role does with its rows after the upgrade, as its service does
MODULE_WORK = {
    "qualification": f"""
        INSERT INTO qualification.qualification_answer (id, "qualificationId", "toolId", "questionId", answer)
             VALUES ('upgrade-probe', '{CARD}', 'annex-1', 'q-probe', 'yes');
        UPDATE qualification.qualification SET description = 'corrected in place' WHERE id = '{CARD}';""",
    "controls": """
        UPDATE controls.submission_answer SET answer = 'No' WHERE id = 'a1';
        DELETE FROM controls.submission_answer WHERE id = 'a1';""",
    "control_objectives": """
        UPDATE control_objectives.project SET name = 'Renamed' WHERE id = 'a1';""",
    "report_composer": """
        UPDATE report_composer.layout SET name = 'Renamed' WHERE name = 'Kept layout';""",
    "engine": """
        SELECT count(*) FROM engine.aisc_backend_evaluation; SELECT count(*) FROM engine.django_migrations;""",
}


@pytest.mark.parametrize("schema,role", sorted(ib.MODULES.items()))
def test_each_module_role_still_reads_and_writes_its_rows(bed, schema, role):
    assert _as(bed, DB_A, role, f"""
        BEGIN;
        SELECT count(*) FROM project.system;
        {MODULE_WORK[schema]}
        ROLLBACK;""") == ""


@pytest.mark.parametrize("schema,role", sorted(ib.MODULES.items()))
def test_each_module_role_no_longer_changes_its_schema(bed, schema, role):
    assert "permission denied" in _as(bed, DB_A, role, f"CREATE TABLE {schema}.upgrade_probe (id int)")


@pytest.mark.parametrize("schema", sorted(ib.MODULES))
def test_each_migrator_still_migrates_its_schema(bed, schema):
    assert _as(bed, DB_A, f"{schema}_migrator", f"""
        BEGIN;
        CREATE TABLE {schema}.upgrade_probe (id int); DROP TABLE {schema}.upgrade_probe;
        ROLLBACK;""") == ""


def test_a_card_is_corrected_by_a_new_revision_and_the_old_one_is_kept(bed):
    """A correction is a new revision of the same version, written as qualification_rw; the revision it
    replaces is kept as it was, and no card is deleted."""
    assert _as(bed, DB_A, "qualification_rw", f"""
        BEGIN;
        INSERT INTO qualification.qualification (id, "systemName", "systemVersion", company, description,
               "targetUseCase", "targetUsers", updated_at, system_id, revision, amends_id, amend_reason,
               amend_requested_by)
        SELECT 'correction', "systemName", "systemVersion", company, 'corrected', "targetUseCase",
               "targetUsers", now(), system_id, revision + 1, id, 'a typo', 'alice'
          FROM qualification.qualification WHERE id = '{CARD}';
        SELECT 1 / (SELECT count(*)::int - 1 FROM qualification.qualification WHERE system_id = '{V2}');
        ROLLBACK;""") == ""
    replaced = _as(bed, DB_A, "qualification_rw", f"""
        BEGIN;
        INSERT INTO qualification.qualification (id, "systemName", "systemVersion", company, description,
               "targetUseCase", "targetUsers", updated_at, system_id, revision, amends_id, amend_reason,
               amend_requested_by)
        SELECT 'correction', "systemName", "systemVersion", company, 'corrected', "targetUseCase",
               "targetUsers", now(), system_id, revision + 1, id, 'a typo', 'alice'
          FROM qualification.qualification WHERE id = '{CARD}';
        UPDATE qualification.qualification SET description = 'rewritten' WHERE id = '{CARD}';
        ROLLBACK;""")
    assert "kept as it was" in replaced, replaced
    assert "is kept" in _as(bed, DB_A, None, f"DELETE FROM qualification.qualification WHERE id = '{CARD}'")


def test_a_run_keeps_the_card_version_it_started_on(bed):
    assert "fixed at its start" in _as(bed, DB_A, "engine_rw", f"""
        BEGIN;
        INSERT INTO engine.aisc_backend_project (pid, name, description, status, project_id, created_at)
             VALUES (gen_random_uuid(), 'upgrade', '', 'Created', '{A}', now());
        INSERT INTO engine.aisc_backend_evaluation (pid, status, project_id, system_id, created_at)
             SELECT gen_random_uuid(), 'Processing', id, '{V1}', now() FROM engine.aisc_backend_project
              WHERE name = 'upgrade';
        UPDATE engine.aisc_backend_evaluation SET system_id = '{V2}' WHERE system_id = '{V1}';
        ROLLBACK;""")


def test_a_card_version_a_module_names_cannot_be_deleted(bed):
    for db in (DB_A, DB_B):
        kinds = bed.scalar(db, "SELECT string_agg(DISTINCT confdeltype::text, '') FROM pg_constraint"
                               " WHERE confrelid = 'project.system'::regclass AND connamespace::regnamespace::text"
                               " IN ('qualification', 'controls', 'control_objectives', 'engine', 'report_composer')")
        assert kinds == "r", (db, kinds)


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
