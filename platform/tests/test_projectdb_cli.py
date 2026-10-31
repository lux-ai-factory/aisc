"""`python -m platform_service.projectdb provision|drop <pid> --dsn ...`: the test beds make a project's
database with the platform's own code, so a bed's database has exactly the layout provisioning gives one,
ledger.platform_action included."""
from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import psycopg
from psycopg.conninfo import make_conninfo

from platform_service import projectdb
from platform_service.ledger.registry import REGISTRY
from tests.conftest import DSN, needs_database

pytestmark = needs_database

PLATFORM_DIR = Path(__file__).resolve().parent.parent


def cli(*args):
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(PLATFORM_DIR), str(PLATFORM_DIR.parent / "shared/identity")])}
    return subprocess.run([sys.executable, "-m", "platform_service.projectdb", *args], cwd=PLATFORM_DIR, env=env,
                          capture_output=True, text=True, timeout=300)


def exists(name: str) -> bool:
    with psycopg.connect(DSN) as conn:
        return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone() is not None


def test_provision_then_drop_from_the_command_line():
    pid = str(uuid.uuid4())
    name = projectdb.database_name(pid)
    done = cli("provision", pid, "--dsn", DSN)
    try:
        assert done.returncode == 0, done.stderr[-2000:]
        assert done.stdout.strip() == name
        with psycopg.connect(make_conninfo(DSN, dbname=name)) as conn:
            applied = {r[0] for r in conn.execute("SELECT name FROM provision.template_migration")}
            actions = {r[0] for r in conn.execute("SELECT name FROM ledger.platform_action")}
        assert applied == {p.name for p in projectdb.TEMPLATE.glob("*.sql")}
        assert actions == {n for n, a in REGISTRY.items() if a.origin != "app"}
    finally:
        gone = cli("drop", pid, "--dsn", DSN)
    assert gone.returncode == 0, gone.stderr[-2000:]
    assert not exists(name)


def test_the_command_line_refuses_what_is_not_a_pid():
    done = cli("provision", "project_x; DROP DATABASE platform", "--dsn", DSN)
    assert done.returncode == 2
    assert "not a project id" in done.stderr


def test_the_command_line_says_how_to_use_it():
    done = cli("make", str(uuid.uuid4()))
    assert done.returncode == 2
    assert "provision" in done.stderr and "drop" in done.stderr
