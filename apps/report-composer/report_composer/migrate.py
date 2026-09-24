"""The composer's own migrations, in its schema report_composer (report run 2026-09-23, R4.1.3, D13).

The same runner as platform/platform_service/migrate.py: ordered .sql files, applied once,
recorded in a table, under an advisory lock. The schema is made by init/report-roles.sql and
owned by report_composer_rw; here it is only read.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"
_LOCK = 8_190_233_707


def pending(applied: set[str], directory: Path = MIGRATIONS) -> list[Path]:
    return [f for f in sorted(directory.glob("*.sql")) if f.name not in applied]


def migrate(conn, directory: Path = MIGRATIONS, table: str = "report_composer.schema_migration") -> list[str]:
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK,))
        schema = table.split(".")[0]
        exists = conn.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (schema,)).fetchone()
        if not exists:
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
