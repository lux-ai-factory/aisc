"""A card version belongs to its project, whatever order the migrations run in.

The rule: qualification.qualification, control_objectives.project, report_composer.layout
and report_composer.generated_report point (system_id, project_id) at core.system
(pid, project_id). The key needs core.system's unique (pid, project_id), which only the
platform side can make, and on a stack the steps below start in no fixed order:

  S  postgres-setup: init/project-databases.sql as the superuser (makes the unique if it is
     missing, then adds any module key a module migration had to leave out)
  P  the platform's migrations (0004 makes the unique if it is missing)
  Q  qualification: prisma migrate deploy
  C  control-objectives: alembic upgrade head
  R  report-composer: its runner, as at its start

Two starting points: a fresh volume (init/platform-db.sql has made the unique before anyone
connects) and the live shape (a volume made before this change: no unique, every module at
the head it has today, a consistent row in each table). After every order the four keys and
the unique exist, and the constraints of core and the three module schemas are the same as
after every other order from that starting point.

Run from the repo root:

    uv run --no-project --with pytest --with psycopg[binary] python -m pytest -q -p no:cacheprovider \
        scripts/tests/test_card_version_keys_orders.py

Every database is a throwaway postgres:14-alpine container, never the host's 5432.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import psycopg
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/pipeline_chain"))
from throwaway import Throwaway  # noqa: E402

QUAL = ROOT / "apps/qualification"
CO = ROOT / "apps/control-objectives"
RC = ROOT / "apps/report-composer"
PRISMA = QUAL / "node_modules/.bin/prisma"

#: What exists on the live stack today, before this change.
LIVE_PLATFORM = ["0001_project_membership.sql", "0002_one_ai_system_per_project.sql",
                 "0003_card_versions_in_core_system.sql"]
LIVE_QUAL_NEW = "20260924120000_a_card_is_of_a_version_of_its_project"   # left out of the live shape
LIVE_CO = "4d2a9c1e7b60"
LIVE_RC = ["0001_report_composer.sql", "0002_templates_are_looks.sql"]

UNIQUE = "system_pid_project_id_key"
PAIR = "FOREIGN KEY (system_id, project_id) REFERENCES core.system(pid, project_id)"
KEYS = {
    ("qualification.qualification", "qualification_system_id_project_id_fkey"): PAIR + " ON DELETE CASCADE",
    ("control_objectives.project", "fk_project_system_id_project_id_core_system"): PAIR + " ON DELETE CASCADE",
    ("report_composer.layout", "layout_system_id_project_id_fkey"): PAIR,
    ("report_composer.generated_report", "generated_report_system_id_project_id_fkey"): PAIR,
}

PROJECT = "0000000c-0000-4000-8000-00000000000a"
VERSION = "0000000c-0000-4000-8000-0000000000a1"
SEED = f"""
INSERT INTO core.project (pid, name, slug) VALUES ('{PROJECT}', 'MCAS', 'mcas');
INSERT INTO core.system (pid, project_id, number, name) VALUES ('{VERSION}', '{PROJECT}', 1, 'MCAS');
INSERT INTO qualification.qualification (id, project_id, system_id, "systemName", "systemVersion", company,
   description, "targetUseCase", "targetUsers", updated_at)
  VALUES ('card', '{PROJECT}', '{VERSION}', 'MCAS', '1', 'LIST', 'd', 'u', 'u', now());
INSERT INTO control_objectives.project (id, project_id, system_id, name, objectives_digest, created_at, updated_at)
  VALUES ('co', '{PROJECT}', '{VERSION}', 'MCAS', '', now(), now());
INSERT INTO report_composer.layout (id, project_id, system_id, name, created_by, updated_by)
  VALUES ('0000000c-0000-4000-8000-0000000000b1', '{PROJECT}', '{VERSION}', 'L', 'a', 'a');
INSERT INTO report_composer.generated_report (layout_id, layout_revision, project_id, system_id, snapshot,
   status, created_by)
  VALUES ('0000000c-0000-4000-8000-0000000000b1', 1, '{PROJECT}', '{VERSION}', '{{}}', 'done', 'a');
"""

LIVE_ORDERS = ["SPQCR", "QCRSP", "QCRPS", "PQCRS", "QSCPR", "CRPQS", "RQPCS", "PSRCQ"]
#: C comes after P in every fresh order: control-objectives' 4d2a9c1e7b60 reads core.system.number,
#: which platform 0003 makes, so on a fresh volume its compose loop retries until the platform has
#: migrated. That was so before this change and is not what is tested here.
FRESH_ORDERS = ["QRPSC", "PSQCR", "RQSPC"]


def _runner(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.migrate


platform_migrate = _runner(ROOT / "platform/platform_service/migrate.py", "platform_migrate")
composer_migrate = _runner(RC / "report_composer/migrate.py", "composer_migrate")


def _only(directory: Path, names: list[str]) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="orders-"))
    for n in names:
        shutil.copy(directory / n, tmp / n)
    return tmp


def _run(cmd, cwd, env):
    r = subprocess.run(cmd, cwd=cwd, env={**os.environ, **env}, capture_output=True, text=True, timeout=600)
    assert r.returncode == 0, f"{cmd} failed:\n{r.stdout[-2000:]}\n{r.stderr[-2000:]}"


class Stack:
    def __init__(self, t: Throwaway):
        self.t = t

    def su(self, sql: str, db: str = "platform"):
        r = self.t.psql(db, sql, check=False)
        assert r.returncode == 0, r.stderr[-3000:]

    def su_file(self, path: Path, db: str = "platform"):
        self.su(path.read_text(), db)

    def connect(self, role: str):
        return psycopg.connect(self.t.dsn(role, "platform"))

    # the steps
    def S(self):
        self.su_file(ROOT / "init/project-databases.sql")

    def P(self, directory: Path | None = None):
        with self.connect("platform_rw") as conn:
            platform_migrate(conn, directory or ROOT / "platform/migrations")

    def Q(self, prisma_dir: Path | None = None):
        schema = (prisma_dir or QUAL / "prisma") / "schema.prisma"
        _run([str(PRISMA), "migrate", "deploy", "--schema", str(schema)], QUAL,
             {"DATABASE_URL": self.t.dsn("qualification_rw", "platform") + "?schema=qualification"})

    def C(self, rev: str = "head"):
        _run(["uv", "run", "--quiet", "alembic", "upgrade", rev], CO,
             {"DATABASE_URL": self.t.dsn("control_objectives_rw", "platform").replace(
                 "postgresql://", "postgresql+psycopg://")})

    def R(self, directory: Path | None = None):
        with self.connect("report_composer_rw") as conn:
            composer_migrate(conn, directory or RC / "pre_isolation_migrations")

    def snapshot(self, name: str):
        self.su(f'DROP DATABASE IF EXISTS "{name}"', "postgres")
        self.su(f'CREATE DATABASE "{name}" TEMPLATE platform', "postgres")

    def restore(self, name: str):
        self.su("DROP DATABASE platform WITH (FORCE)", "postgres")
        self.su(f'CREATE DATABASE platform TEMPLATE "{name}"', "postgres")

    def constraints(self) -> list[tuple[str, str, str]]:
        with psycopg.connect(f"host=127.0.0.1 port={self.t.port} dbname=platform user=aisc-postgres-user"
                             f" password={self.t.password}") as conn:
            return [tuple(r) for r in conn.execute(
                "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint"
                " WHERE connamespace::regnamespace::text IN"
                "   ('core', 'qualification', 'control_objectives', 'report_composer')"
                " ORDER BY 1, 2").fetchall()]


def _fresh(stack: Stack):
    """What docker-entrypoint-initdb.d runs on a new volume, before anyone can connect."""
    stack.su_file(ROOT / "init/platform-db.sql", "postgres")
    stack.S()
    stack.su_file(ROOT / "init/report-roles.sql")


def _live(stack: Stack):
    """A volume made before this change, with every module at today's head and one row each."""
    stack.su_file(ROOT / "init/platform-db.sql", "postgres")
    stack.su(f"ALTER TABLE core.system DROP CONSTRAINT {UNIQUE}")
    stack.su("ALTER TABLE core.system OWNER TO platform_rw")   # what postgres-setup did until now
    stack.su_file(ROOT / "init/report-roles.sql")
    stack.P(_only(ROOT / "platform/migrations", LIVE_PLATFORM))
    prisma = Path(tempfile.mkdtemp(prefix="orders-prisma-")) / "prisma"
    shutil.copytree(QUAL / "prisma", prisma)
    shutil.rmtree(prisma / "migrations" / LIVE_QUAL_NEW)
    stack.Q(prisma)
    stack.C(LIVE_CO)
    stack.R(_only(RC / "pre_isolation_migrations", LIVE_RC))
    stack.su("SET session_replication_role = replica;\n" + SEED)


@pytest.fixture(scope="module")
def stack():
    t = Throwaway.start("orders")
    try:
        assert t.port != 5432
        yield Stack(t)
    finally:
        t.stop()


def _check(stack: Stack, order: str):
    cons = stack.constraints()
    by_name = {(table, name): definition for table, name, definition in cons}
    assert by_name.get(("core.system", UNIQUE)) == "UNIQUE (pid, project_id)", order
    for key, definition in KEYS.items():
        assert by_name.get(key) == definition, (order, key, by_name.get(key))
    return cons


def _orders(stack: Stack, build, fixture: str, orders: list[str]):
    stack.su("DROP DATABASE IF EXISTS platform WITH (FORCE)", "postgres")
    stack.su("CREATE DATABASE platform", "postgres")
    build(stack)
    stack.snapshot(fixture)
    seen = {}
    for order in orders:
        stack.restore(fixture)
        for step in order:
            getattr(stack, step)()
        seen[order] = _check(stack, order)
    first = orders[0]
    for order in orders[1:]:
        assert seen[order] == seen[first], f"order {order} ends with other constraints than {first}"
    return seen


def test_every_order_from_a_fresh_volume_ends_with_the_keys(stack):
    _orders(stack, _fresh, "fixture_fresh", FRESH_ORDERS)


def test_every_order_from_the_live_shape_ends_with_the_keys(stack):
    _orders(stack, _live, "fixture_live", LIVE_ORDERS)
    # the seeded rows are still there, and still satisfy the keys
    assert stack.t.scalar("platform", "SELECT count(*) FROM report_composer.generated_report") == "1"


def test_a_module_that_migrated_first_gets_its_key_from_the_next_postgres_setup(stack):
    """The live shape, modules first: they leave their keys out; then S adds them."""
    if stack.t.scalar("postgres", "SELECT count(*) FROM pg_database WHERE datname = 'fixture_live'") != "1":
        stack.su("DROP DATABASE IF EXISTS platform WITH (FORCE)", "postgres")
        stack.su("CREATE DATABASE platform", "postgres")
        _live(stack)
        stack.snapshot("fixture_live")
    stack.restore("fixture_live")
    stack.Q()
    stack.C()
    stack.R()
    names = {name for _table, name, _def in stack.constraints()}
    assert not names & {name for _table, name in KEYS}
    stack.S()
    _check(stack, "QCR then S")
