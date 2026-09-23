"""A database per project: its name, making it, and removing it.

The database is the project. Every module keeps its data for a project in that
project's database, so a query that forgets to filter still cannot reach
another project: it is connected to the wrong place to do it.
"""
from __future__ import annotations

import re
from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo

from platform_service.migrate import migrate

TEMPLATE = Path(__file__).resolve().parent.parent / "project-template"
TRACKING_TABLE = "provision.template_migration"
_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class NotAPid(ValueError):
    """Only a project id may name a database: anything else is refused unread."""


def database_name(pid: str | UUID) -> str:
    text = str(pid).lower()
    if not _PID.match(text):
        raise NotAPid(f"not a project id: {text!r}")
    return "project_" + text.replace("-", "")


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
    return name


def drop(base_dsn: str, pid: str | UUID) -> None:
    name = database_name(pid)
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
