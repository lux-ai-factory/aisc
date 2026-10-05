"""verify-dump: prove the dump files taken before the shared schemas are dropped, row by row.

The dump files (one of the four module schemas, one of core.system; pg_dump ignores -n
when -t is given) are restored with `pg_restore` from PATH into a database made for it,
and `verify` then runs with that database as the source of the moving tables (the
library tables are still read from `platform`). The database is dropped in any case.
"""
from __future__ import annotations

import logging
import secrets
import subprocess

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from . import rowtext as R
from .catalog import read_tables

log = logging.getLogger("platform_service.isolate")


def _holds_core_system(path: str) -> bool:
    p = subprocess.run(["pg_restore", "--list", path], capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"pg_restore --list failed on a dump file (exit {p.returncode})")
    return any(" TABLE core system " in line for line in p.stdout.splitlines())


def _prepare(su: str, restore_dsn: str) -> None:
    """core.project (its rows copied from the source) and core.system_only_latest_changes(),
    which the core.system dump's trigger needs."""
    with psycopg.connect(su, autocommit=True) as src, psycopg.connect(restore_dsn, autocommit=True) as dst:
        t = read_tables(src, ["core"])["core.project"]
        dst.execute("CREATE SCHEMA core")
        cols = sql.SQL(", ").join(
            sql.SQL("{} {}{}").format(sql.Identifier(c.name), sql.SQL(c.type),
                                      sql.SQL(" NOT NULL") if c.not_null else sql.SQL(""))
            for c in t.columns)
        dst.execute(sql.SQL("CREATE TABLE core.project ({}, PRIMARY KEY ({}))").format(cols, R.cols_sql(t.pk)))
        out = sql.SQL("COPY core.project ({}) TO STDOUT").format(R.cols_sql(t.column_names))
        into = sql.SQL("COPY core.project ({}) FROM STDIN").format(R.cols_sql(t.column_names))
        with src.cursor().copy(out) as reader, dst.cursor().copy(into) as writer:
            for block in reader:
                writer.write(block)
        fn = src.execute("SELECT pg_get_functiondef(to_regprocedure('core.system_only_latest_changes()'))").fetchone()
        if fn and fn[0]:
            dst.execute(fn[0])


def verify_dump(a, su: str, run_class):
    name = "isolate_verify_" + secrets.token_hex(6)
    restore_dsn = make_conninfo(su, dbname=name)
    with psycopg.connect(su, autocommit=True) as c:
        c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    run = None
    try:
        _prepare(su, restore_dsn)
        files = sorted(a.dumps, key=lambda f: 0 if _holds_core_system(f) else 1)
        for f in files:
            p = subprocess.run(["pg_restore", "--no-owner", "--no-acl", "--exit-on-error", "--single-transaction",
                                "-d", restore_dsn, f], capture_output=True, text=True)
            if p.returncode != 0:  # its stderr can quote rows: not printed
                raise RuntimeError(f"pg_restore failed on a dump file (exit {p.returncode})")
        log.info("restored %s dump file(s) into a verify database", len(files))
        run = run_class(a, su, source_dsn=restore_dsn)
        code = run.verify()
        run.close()
        return run, code
    finally:
        if run is not None:
            run.close()
        with psycopg.connect(su, autocommit=True) as c:
            c.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name)))
