"""One database per project.

Everything of a project (its versions in project.system, its layouts, templates and reports) is read and
written over REPORT_COMPOSER_PROJECT_DATABASE_URL, a DSN with `{database}` in place of the database
name, filled with `project_<pid without hyphens>`. A project database is opened only after
guards.guard has decided membership for that pid (the callers open it inside the guarded route).

One connection per call, one transaction, closed on exit: no pool. The first open of a database
in this process migrates it first (lock 8_190_233_707 in that database, the history re-read inside the
lock), unless the start loop already did; it migrates as report_composer_migrator, over
REPORT_COMPOSER_PROJECT_MIGRATE_DATABASE_URL.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Iterator

import psycopg
from aisc_identity.projectdb import NotAPid
from aisc_identity.projectdb import database_name as shared_database_name
from psycopg.rows import dict_row

from . import db, migrate
from .errors import ApiError

PLACEHOLDER = "{database}"
NO_PROJECT = "No such project."
UNAVAILABLE = "This project's reports cannot be reached just now."


def database_name(pid: str) -> str:
    """project_<32 lowercase hex digits>, by the shared rule; anything but a canonical uuid is refused with a
    ValueError (aisc_identity.projectdb.NotAPid)."""
    if not isinstance(pid, str):
        raise NotAPid("not a project pid")
    return shared_database_name(pid)


def dsn_for(template: str, name: str) -> str:
    if not template or PLACEHOLDER not in template:
        raise ValueError("REPORT_COMPOSER_PROJECT_DATABASE_URL must contain {database}")
    return template.replace(PLACEHOLDER, name)


class ProjectDatabases:
    def __init__(self, template: str, platform_url: str, migrate_template: str | None = None) -> None:
        self.template = template or ""
        self.platform_url = platform_url
        #: the migrator's template (REPORT_COMPOSER_PROJECT_MIGRATE_DATABASE_URL): a database is migrated
        #: through it and queried through `template`; None migrates on the query role (a scratch bed)
        self.migrate_template = migrate_template or None
        self._migrated: set[str] = set()
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def dsn(self, pid: str) -> str:
        return dsn_for(self.template, database_name(pid))

    def exists(self, pid: str) -> bool:
        with psycopg.connect(self.platform_url, connect_timeout=db.CONNECT_TIMEOUT_S) as conn:
            return conn.execute("SELECT 1 FROM pg_database WHERE datname = %s",
                                (database_name(pid),)).fetchone() is not None

    def mark_migrated(self, name: str) -> None:
        with self._guard:
            self._migrated.add(name)

    def forget(self, pid: str) -> None:
        with self._guard:
            self._migrated.discard(database_name(pid))

    def _lock_for(self, name: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(name, threading.Lock())

    def _refused(self, pid: str) -> ApiError:
        """A connect error: 404 when the database is gone (the project was deleted), else 503. The error text is not parsed."""
        try:
            gone = not self.exists(pid)
        except psycopg.Error:
            return ApiError(503, "unavailable", UNAVAILABLE)
        if gone:
            self.forget(pid)
            return ApiError(404, "not_found", NO_PROJECT)
        return ApiError(503, "unavailable", UNAVAILABLE)

    def _open(self, pid: str, *, migrating: bool = False):
        try:
            dsn = (dsn_for(self.migrate_template, database_name(pid)) if migrating and self.migrate_template
                   else self.dsn(pid))
        except ValueError:  # the template has no {database}: a configuration error, not the caller's
            raise ApiError(503, "unavailable", UNAVAILABLE) from None
        try:
            # through the module attribute: the tests' spies replace psycopg.connect
            return psycopg.connect(dsn, row_factory=dict_row, connect_timeout=db.CONNECT_TIMEOUT_S)
        except psycopg.OperationalError:
            raise self._refused(pid) from None

    def _migrate_once(self, pid: str, name: str) -> None:
        if name in self._migrated:
            return
        with self._lock_for(name):
            if name in self._migrated:
                return
            conn = self._open(pid, migrating=True)
            try:
                with conn:
                    migrate.migrate_project(conn)
            except (migrate.SchemaMissing, migrate.SchemaNotOwned):
                raise ApiError(503, "unavailable", UNAVAILABLE) from None
            finally:
                conn.close()
            self.mark_migrated(name)

    @contextmanager
    def connect(self, pid: str) -> Iterator[psycopg.Connection]:
        """One transaction on the project's database: committed at the end, rolled back on an exception."""
        try:
            name = database_name(pid)
        except ValueError:
            raise ApiError(404, "not_found", NO_PROJECT) from None
        self._migrate_once(pid, name)
        conn = self._open(pid)
        with conn:
            yield conn
