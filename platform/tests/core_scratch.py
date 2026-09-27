"""Scratch copies of the platform database, for the tests of core migrations.

A migration test needs a database in a known state: fresh, or shaped like the
live one before a migration ran. The shared test database has already been
migrated by the time those tests run, so each of them makes its own database
next to it, prepared the way the live one was (init/platform-db.sql as the
superuser, then platform migrations as platform_rw), and drops it afterwards.

Making a database and running init/platform-db.sql take the superuser, so these
tests need PLATFORM_TEST_SUPERUSER_URL (the throwaway container's superuser
DSN). Without it they skip. It must never point at the live database.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from platform_service.migrate import MIGRATIONS, migrate

REPO = Path(__file__).resolve().parents[2]
PLATFORM_DB_SQL = REPO / "init" / "platform-db.sql"
#: The pre-isolation init/platform-db.sql (f01288a), which still made core.system and the module
#: schemas: the layout the migration tests of core.system pin (03-coding-plan.md G3).
PRE_ISOLATION_PLATFORM_DB_SQL = REPO / "scripts" / "tests" / "fixtures" / "isolation" / "pre_isolation_platform_db.sql"
PROJECT_DATABASES_SQL = REPO / "init" / "project-databases.sql"

SUPERUSER_DSN = os.environ.get("PLATFORM_TEST_SUPERUSER_URL")

needs_superuser = pytest.mark.skipif(
    not SUPERUSER_DSN, reason="PLATFORM_TEST_SUPERUSER_URL is not set (throwaway superuser DSN)"
)


def _refuse_live(dsn: str) -> None:
    port = str(conninfo_to_dict(dsn).get("port", "5432"))
    if port == "5432":
        raise RuntimeError(f"refusing to run migration tests against port 5432 (live): {dsn!r}")


def platform_db_sql_for(dbname: str, old_layout: bool = False) -> str:
    """init/platform-db.sql (or, with old_layout, its pre-isolation version), aimed
    at `dbname` instead of `platform`.

    Only the psql meta-commands (which psycopg cannot run) and the database
    name change; every statement that makes core and its grants is kept.
    """
    text = (PRE_ISOLATION_PLATFORM_DB_SQL if old_layout else PLATFORM_DB_SQL).read_text()
    text = re.sub(r"SELECT 'CREATE DATABASE platform'.*?\\gexec\n", "", text, flags=re.S)
    text = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("\\"))
    return re.sub(r"DATABASE platform\b", f"DATABASE {dbname}", text)


def project_databases_platform_part() -> str:
    """The part of init/project-databases.sql that runs in the platform
    database: everything before its first `\\connect` elsewhere, or after a
    `\\connect platform`. Meta-commands are dropped."""
    out, in_platform = [], True
    for line in PROJECT_DATABASES_SQL.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("\\connect") or stripped.startswith("\\c "):
            in_platform = stripped.split()[-1] == "platform"
            continue
        if stripped.startswith("\\"):
            continue
        if in_platform:
            out.append(line)
    return "\n".join(out)


@contextmanager
def scratch_database(old_layout: bool = False):
    """A new database, prepared by init/platform-db.sql as the superuser.
    Yields (superuser_dsn, platform_rw_dsn) for it; dropped afterwards.

    old_layout: prepared by the pre-isolation init/platform-db.sql instead, which
    made core.system and the module schemas in the platform database. The tests of
    the migrations of core.system pin that history, which exists only there
    (isolation 2026-09-25: a fresh volume no longer makes core.system, I2.8)."""
    _refuse_live(SUPERUSER_DSN)
    name = f"pytest_core_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(SUPERUSER_DSN, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    su = make_conninfo(SUPERUSER_DSN, dbname=name)
    rw = make_conninfo(SUPERUSER_DSN, dbname=name, user="platform_rw", password="platform_rw")
    try:
        with psycopg.connect(su, autocommit=True) as conn:
            conn.execute(platform_db_sql_for(name, old_layout))
        yield su, rw
    finally:
        with psycopg.connect(SUPERUSER_DSN, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def apply_platform_migrations(rw_dsn: str, upto: str | None = None) -> list[str]:
    """Run platform migrations as platform_rw, as platform_service does.
    `upto` is the last file name to include (e.g. "0002"); None means all."""
    if upto is None:
        with psycopg.connect(rw_dsn) as conn:
            return migrate(conn)
    tmp = Path(tempfile.mkdtemp(prefix="pytest-migrations-"))
    try:
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name[: len(upto)] <= upto:
                shutil.copy(path, tmp / path.name)
        with psycopg.connect(rw_dsn) as conn:
            return migrate(conn, tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def give_core_system_to_platform(su_dsn: str) -> None:
    """What the ownership line in init/project-databases.sql does (D1)."""
    with psycopg.connect(su_dsn, autocommit=True) as conn:
        conn.execute("ALTER TABLE core.system OWNER TO platform_rw")
