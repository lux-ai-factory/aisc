"""A database per project: its name, making it, and removing it.

The database is the project. Every module keeps its data for a project in that
project's database, so a query that forgets to filter still cannot reach
another project: it is connected to the wrong place to do it.
"""
from __future__ import annotations

from pathlib import Path
from uuid import UUID

import psycopg
from psycopg import errors, sql
from psycopg.conninfo import make_conninfo

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


def provision(base_dsn: str, pid: str | UUID) -> str:
    """Make this project's database if it is missing, and bring its template
    up to date. Safe to call again: that is how existing projects get theirs."""
    return provision_as(base_dsn, pid)


def provision_as(base_dsn: str, pid: str | UUID, *, set_role: str | None = None,
                 owner: str | None = None) -> str:
    """provision(), for a caller that is not the platform's own role.

    The move tool (`python -m platform_service.isolate provision`) connects as the
    superuser: `owner` makes the database owned by that role (as if the platform had
    made it), and `set_role` applies the template as that role, so every schema the
    template makes is owned by it too (01-specs.md D10, 02-tests.md S-D4). Without
    either this is exactly provision()."""
    name = database_name(pid)
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            create = sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
            if owner is not None:
                create = sql.SQL("{} OWNER {}").format(create, sql.Identifier(owner))
            try:
                conn.execute(create)
            except errors.DuplicateDatabase:
                pass  # another instance made it between the check and here
    with psycopg.connect(make_conninfo(base_dsn, dbname=name)) as conn:
        if set_role is not None:
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(set_role)))
        migrate(conn, TEMPLATE, TRACKING_TABLE)
        sync_platform_actions(conn)
    return name


def sync_platform_actions(conn) -> None:
    """Keep ledger.platform_action equal to the registry's actions no app may emit (origin platform or
    browser), so ledger.emit refuses exactly those (template 0020; spec 6.4, n11)."""
    from platform_service.ledger.registry import REGISTRY

    names = sorted(name for name, action in REGISTRY.items() if action.origin != "app")
    with conn.transaction():
        conn.execute("DELETE FROM ledger.platform_action WHERE NOT (name = ANY(%s))", (names,))
        for name in names:
            conn.execute("INSERT INTO ledger.platform_action (name) VALUES (%s) ON CONFLICT DO NOTHING", (name,))


#: The one function templates 0007..0010 call to set a module role's search_path in
#: their database (init/project-databases.sql, 03-coding-plan.md P1-D1).
SETUP_FUNCTION = "aisc_setup.apply_role_setting(text)"


def install_setup_function(su_conn_to_target: psycopg.Connection, template1_dsn: str) -> bool:
    """Put aisc_setup.apply_role_setting into a database made before
    init/project-databases.sql put it into template1 (the ones made since have it).

    `su_conn_to_target` is a superuser connection to that database (the function must
    be owned by the superuser: it is SECURITY DEFINER); the definition is read from
    template1, so there is one text of it. Returns whether it was installed; a
    database that has it already is left as it is. Raises when template1 lacks it."""
    have = su_conn_to_target.execute("SELECT to_regprocedure(%s)", (SETUP_FUNCTION,)).fetchone()[0]
    if have is not None:
        return False
    with psycopg.connect(make_conninfo(template1_dsn, dbname="template1")) as t1:
        found = t1.execute("SELECT pg_get_functiondef(to_regprocedure(%s))", (SETUP_FUNCTION,)).fetchone()
    if found is None or found[0] is None:
        raise RuntimeError(f"template1 has no {SETUP_FUNCTION}: run init/project-databases.sql first")
    with su_conn_to_target.transaction():
        su_conn_to_target.execute("CREATE SCHEMA IF NOT EXISTS aisc_setup")
        su_conn_to_target.execute("REVOKE ALL ON SCHEMA aisc_setup FROM PUBLIC")
        su_conn_to_target.execute("GRANT USAGE ON SCHEMA aisc_setup TO platform_rw")
        su_conn_to_target.execute(found[0])
        su_conn_to_target.execute(f"REVOKE ALL ON FUNCTION {SETUP_FUNCTION} FROM PUBLIC")
        su_conn_to_target.execute(f"GRANT EXECUTE ON FUNCTION {SETUP_FUNCTION} TO platform_rw")
    return True


def drop(base_dsn: str, pid: str | UUID) -> None:
    name = database_name(pid)
    with psycopg.connect(base_dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
