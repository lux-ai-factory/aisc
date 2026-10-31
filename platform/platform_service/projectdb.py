"""A database per project: its name, making it, opening it, and removing it.

The database is the project. Every module keeps its data for a project in that
project's database, so a query that forgets to filter still cannot reach
another project: it is connected to the wrong place to do it.

The test beds make and drop one the way the platform does, from `platform/`:

    python -m platform_service.projectdb provision|drop <pid> --dsn <the platform database, as platform_rw>
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row

from platform_service.migrate import migrate
from platform_service.projects import PID

TEMPLATE = Path(__file__).resolve().parent.parent / "project-template"
TRACKING_TABLE = "provision.template_migration"


class NotAPid(ValueError):
    """Only a project id may name a database: anything else is refused unread."""


def database_name(pid: str | UUID) -> str:
    text = str(pid).lower()
    if not PID.fullmatch(text):
        raise NotAPid(f"not a project id: {text!r}")
    return "project_" + text.replace("-", "")


def connect(pid: str | UUID, *, autocommit: bool = False, row_factory=dict_row) -> psycopg.Connection:
    """A new connection to this project's database, as the platform's own role (db.dsn()); row_factory None
    gives tuples.

    Raises db.ProjectDatabaseGone when the database is not there: looked up first, and also when it is
    dropped between that look and the connect."""
    from platform_service import db                                   # db imports this module too

    name = database_name(pid)
    with db.pool().connection() as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
    if exists is None:
        raise db.ProjectDatabaseGone(str(pid))
    options = {"autocommit": autocommit, **({"row_factory": row_factory} if row_factory is not None else {})}
    try:
        return psycopg.connect(make_conninfo(db.dsn(), dbname=name), **options)
    except psycopg.OperationalError as exc:
        if "does not exist" in str(exc) and "database" in str(exc):
            raise db.ProjectDatabaseGone(str(pid)) from None
        raise


def provision(base_dsn: str, pid: str | UUID) -> str:
    """Make this project's database if it is missing, and bring its template
    up to date. Safe to call again: that is how existing projects get theirs."""
    name = database_name(pid)
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            try:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
            except errors.DuplicateDatabase:
                pass  # another instance made it between the check and here
    with psycopg.connect(make_conninfo(base_dsn, dbname=name)) as conn:
        migrate(conn, TEMPLATE, TRACKING_TABLE)
        sync_platform_actions(conn)
    return name


def sync_platform_actions(conn) -> None:
    """Keep ledger.platform_action equal to the registry's actions no app may emit (origin platform or
    browser), so ledger.emit refuses exactly those (project-template/0020_ledger_outbox.sql)."""
    from platform_service.ledger.registry import REGISTRY

    if conn.execute("SELECT to_regclass('ledger.platform_action')").fetchone()[0] is None:
        return                                                        # a template before 0020: nothing to keep
    names = sorted(name for name, action in REGISTRY.items() if action.origin != "app")
    with conn.transaction():
        conn.execute("DELETE FROM ledger.platform_action WHERE NOT (name = ANY(%s))", (names,))
        for name in names:
            conn.execute("INSERT INTO ledger.platform_action (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))


def drop(base_dsn: str, pid: str | UUID) -> None:
    name = database_name(pid)
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m platform_service.projectdb",
                                     description="Make (provision) or remove (drop) a project's database.")
    parser.add_argument("command", choices=("provision", "drop"))
    parser.add_argument("pid")
    parser.add_argument("--dsn", required=True, help="the platform database, as platform_rw")
    args = parser.parse_args(argv)
    try:
        name = database_name(args.pid)
    except NotAPid as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.command == "provision":
        provision(args.dsn, args.pid)
    else:
        drop(args.dsn, args.pid)
    print(name)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
