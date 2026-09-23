"""Migrations for `core`, the one schema every module reads.

Deliberately small: ordered .sql files, applied once, recorded in a table. The
platform service is the only writer of core, so it is the thing that migrates
it, and it does so before serving the first request.

init/platform-db.sql still makes the database, the schemas, the roles and their
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


def pending(applied: set[str]) -> list[Path]:
    return [f for f in sorted(MIGRATIONS.glob("*.sql")) if f.name not in applied]


def migrate(conn) -> list[str]:
    """Apply what has not been applied. Returns the names it ran."""
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
        conn.execute(
            "CREATE TABLE IF NOT EXISTS core.schema_migration ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        applied = {r["name"] for r in conn.execute(
            "SELECT name FROM core.schema_migration"
        ).fetchall()}
        ran = []
        for path in pending(applied):
            logger.info("applying %s", path.name)
            conn.execute(path.read_text())
            conn.execute("INSERT INTO core.schema_migration (name) VALUES (%s)", (path.name,))
            ran.append(path.name)
        return ran
