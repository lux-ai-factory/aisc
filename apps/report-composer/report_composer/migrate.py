"""The composer's own migrations: one history.

    migrations/project/   each project's database, schema report_composer, tracked in
                          report_composer.schema_migration of that database

The same runner as platform/platform_service/migrate.py: ordered .sql files, applied once, recorded in a
table, under advisory lock 8_190_233_707 taken in the database being migrated. The schemas are made by
the platform (template 0010 in a project database); the start loop never makes one, and the composer keeps
nothing in `platform`.

    python -m report_composer.migrate    every project database

It migrates as report_composer_migrator (REPORT_COMPOSER_PROJECT_MIGRATE_DATABASE_URL), whose sessions act
as report_composer_owner, the owner of every table the history makes; the composer reads and writes their
rows as report_composer_rw. A project database is migrated only once its schema is report_composer_owner's
(the platform hands it over after postgres-setup made the role).

Exit status, the convention of every migrate one-shot (the compose loop retries 1 and stops on 2):
0 when every project database is at its head; 1 when the platform database
cannot be reached yet, or a schema is still the platform's (it waits for its owner); 2 for a missing
setting, or when any project database failed (permanent: report-composer does not start on a
half-migrated set).

This file stays loadable on its own (a test loads it with spec_from_file_location): at the top level it
imports only the standard library and psycopg.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

import psycopg

#: seconds a connection attempt may take (psycopg has none): a silent server would hold a migration
#: forever. db.CONNECT_TIMEOUT_S is the same for the app's own connections.
CONNECT_TIMEOUT_S = 10

logger = logging.getLogger(__name__)

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
PROJECT = MIGRATIONS / "project"
PROJECT_TABLE = "report_composer.schema_migration"
_LOCK = 8_190_233_707


class SchemaMissing(RuntimeError):
    """The schema a history belongs to is not there (the platform has not made it yet)."""


#: The role that owns the report_composer schema of a project database and every table in it; the
#: migrator's sessions act as it.
SCHEMA_OWNER = "report_composer_owner"
#: Who holds the schema before the platform hands it to its owner: the platform, which makes it.
NOT_HANDED_OVER_YET = ("platform_rw", "platform_owner")


class SchemaNotOwned(RuntimeError):
    """A project database's report_composer schema is not report_composer_owner's. `wait` is True while it
    is still the platform's (the hand-over is to come: trying again later helps); False for anyone else's."""

    def __init__(self, owner):
        self.owner = owner
        self.wait = owner in NOT_HANDED_OVER_YET
        super().__init__(f"schema report_composer belongs to {owner or 'nobody'}, not {SCHEMA_OWNER}: run"
                         " postgres-setup (init/owner-roles.sql) and start the platform, which hands it over")


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


def check_schema_owner(conn) -> None:
    """In a project database the schema is report_composer_owner's before anything is migrated there
    (SchemaNotOwned otherwise); a scratch database outside the stack is not checked."""
    row = conn.execute("SELECT current_database() ~ '^project_[0-9a-f]{32}$' AS in_project,"
                       " (SELECT pg_get_userbyid(nspowner)::text FROM pg_namespace WHERE nspname = 'report_composer')"
                       " AS owner").fetchone()
    in_project, owner = (row["in_project"], row["owner"]) if isinstance(row, dict) else row
    if in_project and owner is not None and owner != SCHEMA_OWNER:
        raise SchemaNotOwned(owner)


def migrate_project(conn) -> list[str]:
    """The project history, on a connection to one project's database, once its schema is the owner's."""
    check_schema_owner(conn)
    return migrate(conn, PROJECT, PROJECT_TABLE, create_schema=False)


def project_databases(database_url: str) -> list[tuple[str, str]]:
    """(pid, database name) of every project of core.project whose database exists, in pid order."""
    from report_composer.projectdb import database_name

    with psycopg.connect(database_url, connect_timeout=CONNECT_TIMEOUT_S) as conn:
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


def migrate_everything(database_url: str, project_database_url: str) -> dict[str, str]:
    """Every project database: {name: "ok" | "waiting" | "failed: <ExceptionClass>"}. A failed database is
    logged by name and exception class only (its text may hold a DSN), and the loop goes on; one whose
    schema is still the platform's is "waiting". `project_database_url` is the migrator's template."""
    from report_composer.projectdb import dsn_for

    results: dict[str, str] = {}
    for _pid, name in project_databases(database_url):
        try:
            with psycopg.connect(dsn_for(project_database_url, name), connect_timeout=CONNECT_TIMEOUT_S) as conn:
                migrate_project(conn)
            results[name] = "ok"
        except SchemaNotOwned as exc:
            results[name] = "waiting" if exc.wait else f"failed: {type(exc).__name__}"
            logger.error("%s: %s", name, exc)
        except Exception as exc:  # noqa: BLE001
            results[name] = f"failed: {type(exc).__name__}"
            logger.error("migration of %s failed: %s", name, type(exc).__name__)
    return results


#: exit statuses of the one-shot
OK, RETRY, PERMANENT = 0, 1, 2


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    database_url = os.environ.get("REPORT_COMPOSER_DATABASE_URL", "")
    project_database_url = os.environ.get("REPORT_COMPOSER_PROJECT_MIGRATE_DATABASE_URL", "")
    if not database_url or not project_database_url:
        logger.error("REPORT_COMPOSER_DATABASE_URL and REPORT_COMPOSER_PROJECT_MIGRATE_DATABASE_URL (the migrations,"
                     " as report_composer_migrator) must both be set")
        return PERMANENT
    try:
        project_databases(database_url)   # the platform answers, or the loop waits for it
    except psycopg.OperationalError as exc:
        logger.error("the platform database cannot be reached yet: %s", type(exc).__name__)
        return RETRY
    results = migrate_everything(database_url, project_database_url)
    failed = sorted(name for name, r in results.items() if r not in ("ok", "waiting"))
    waiting = sorted(name for name, r in results.items() if r == "waiting")
    logger.info("migrated %d of %d databases", len(results) - len(failed) - len(waiting), len(results))
    for name in failed:
        logger.error("not migrated: %s (%s)", name, results[name])
    if failed:
        return PERMANENT
    if waiting:
        logger.error("%d project database(s) wait for their schema to belong to %s: run postgres-setup, then let"
                     " the platform start", len(waiting), SCHEMA_OWNER)
        return RETRY
    return OK


if __name__ == "__main__":
    sys.exit(main())
