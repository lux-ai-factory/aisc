"""Migrations for `core`, the one schema every module reads.

Ordered .sql files, applied once, recorded in a table. The platform service is
the only writer of core, so it migrates it, before serving the first request.

init/platform-db.sql makes the database, the schemas, the roles and their
grants, because those need a superuser and only happen on a fresh volume.
Everything after that is a file in migrations/.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"

#: One arbitrary, constant key, so two instances starting together do not both
#: apply the same file.
_LOCK = 8_190_233_419


def pending(applied: set[str], directory: Path = MIGRATIONS) -> list[Path]:
    return [f for f in sorted(directory.glob("*.sql")) if f.name not in applied]


def migrate(conn, directory: Path = MIGRATIONS, table: str = "core.schema_migration") -> list[str]:
    """Apply what has not been applied. Returns the names it ran.

    `directory` and `table` let the same runner apply the per-project template
    (platform/project-template/) to a project database, which has no core.
    """
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
        schema = table.split(".")[0]
        # Not unconditional: Postgres checks CREATE privilege on the database
        # for this statement even when the schema already exists, and
        # `platform_rw` has that only in a database it made. `core` predates
        # this role's grants, so it is read here, never (re)created.
        exists = conn.execute(
            "SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)
        ).fetchone()
        if not exists:
            conn.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS {table} ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        applied = {r["name"] if isinstance(r, dict) else r[0]
                   for r in conn.execute(f"SELECT name FROM {table}").fetchall()}
        ran = []
        for path in pending(applied, directory):
            logger.info("applying %s", path.name)
            conn.execute(path.read_text())
            conn.execute(f"INSERT INTO {table} (name) VALUES (%s)", (path.name,))
            ran.append(path.name)
        return ran
