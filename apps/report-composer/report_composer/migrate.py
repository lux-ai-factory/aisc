"""The composer's own migrations: two histories (isolation 2026-09-25, 01-specs.md I8.2, I8.4).

    migrations/project/   each project's database, schema report_composer, tracked in
                          report_composer.schema_migration of that database
    migrations/library/   the install-wide library in `platform`, schema report_library, tracked in
                          report_library.schema_migration

The same runner as platform/platform_service/migrate.py: ordered .sql files, applied once, recorded in a
table, under advisory lock 8_190_233_707 taken in the database being migrated. The schemas are made by
the platform (template 0010 in a project database, the init files for report_library); the start loop
never makes one, so the composer never creates its schema in `platform`.

    python -m report_composer.migrate    the library, then every project database; exit 0 when all are ok

This file stays loadable on its own (a test loads it with spec_from_file_location): at the top level it
imports only the standard library and psycopg.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psycopg

logger = logging.getLogger(__name__)

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
PROJECT = MIGRATIONS / "project"
PROJECT_TABLE = "report_composer.schema_migration"
LIBRARY = MIGRATIONS / "library"
LIBRARY_TABLE = "report_library.schema_migration"
LIBRARY_NAME = "report_library"
_LOCK = 8_190_233_707


class SchemaMissing(RuntimeError):
    """The schema a history belongs to is not there (the platform has not made it yet)."""


def pending(applied: set[str], directory: Path = PROJECT) -> list[Path]:
    return [f for f in sorted(directory.glob("*.sql")) if f.name not in applied]


def migrate(conn, directory: Path = PROJECT, table: str = PROJECT_TABLE, *, create_schema: bool = True) -> list[str]:
    """Apply the pending files of `directory` in one transaction. With create_schema=False a missing
    schema raises SchemaMissing instead of being made."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
        schema = table.split(".")[0]
        exists = conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone()
        if not exists:
            if not create_schema:
                raise SchemaMissing(f"schema {schema} does not exist in this database")
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} ("
                     " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        applied = {r["name"] if isinstance(r, dict) else r[0]
                   for r in conn.execute(f"SELECT name FROM {table}").fetchall()}
        ran = []
        for path in pending(applied, directory):
            logger.info("applying %s", path.name)
            conn.execute(path.read_text())
            conn.execute(f"INSERT INTO {table} (name) VALUES (%s)", (path.name,))
            ran.append(path.name)
        return ran


def migrate_library(conn) -> list[str]:
    """The library history, on a connection to `platform`."""
    return migrate(conn, LIBRARY, LIBRARY_TABLE, create_schema=False)


def migrate_project(conn) -> list[str]:
    """The project history, on a connection to one project's database."""
    return migrate(conn, PROJECT, PROJECT_TABLE, create_schema=False)


def project_databases(database_url: str) -> list[tuple[str, str]]:
    """(pid, database name) of every project of core.project whose database exists, in pid order."""
    from report_composer.projectdb import database_name

    with psycopg.connect(database_url) as conn:
        pids = [str(r[0]) for r in conn.execute("SELECT pid FROM core.project ORDER BY pid").fetchall()]
        existing = {r[0] for r in conn.execute("SELECT datname FROM pg_database").fetchall()}
    out = []
    for pid in pids:
        try:
            name = database_name(pid)
        except ValueError:
            continue
        if name in existing:
            out.append((pid, name))
    return out


def migrate_everything(database_url: str, project_database_url: str, *, library: bool = True) -> dict[str, str]:
    """Optionally the library, then every project database: {name: "ok" | "failed: <ExceptionClass>"}.
    A failed database is logged by name and exception class only, and the loop goes on."""
    from report_composer.projectdb import dsn_for

    results: dict[str, str] = {}
    if library:
        try:
            with psycopg.connect(database_url) as conn:
                migrate_library(conn)
            results[LIBRARY_NAME] = "ok"
        except Exception as exc:  # noqa: BLE001 - reported by class, never by text (it may hold a DSN)
            results[LIBRARY_NAME] = f"failed: {type(exc).__name__}"
            logger.error("migration of %s failed: %s", LIBRARY_NAME, type(exc).__name__)
    for _pid, name in project_databases(database_url):
        try:
            with psycopg.connect(dsn_for(project_database_url, name)) as conn:
                migrate_project(conn)
            results[name] = "ok"
        except Exception as exc:  # noqa: BLE001
            results[name] = f"failed: {type(exc).__name__}"
            logger.error("migration of %s failed: %s", name, type(exc).__name__)
    return results


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    database_url = os.environ.get("REPORT_COMPOSER_DATABASE_URL", "")
    project_database_url = os.environ.get("REPORT_COMPOSER_PROJECT_DATABASE_URL", "")
    if not database_url or not project_database_url:
        logger.error("REPORT_COMPOSER_DATABASE_URL and REPORT_COMPOSER_PROJECT_DATABASE_URL must both be set")
        return 1
    results = migrate_everything(database_url, project_database_url)
    failed = sorted(name for name, r in results.items() if r != "ok")
    logger.info("migrated %d of %d databases", len(results) - len(failed), len(results))
    for name in failed:
        logger.error("not migrated: %s (%s)", name, results[name])
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
