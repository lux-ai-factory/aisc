"""One database per project (isolation 2026-09-25, 01-specs.md I8.1, I8.4, I2.5, I17.1, I1.8).

Everything of a project (its versions in project.system, its layouts, templates and reports) is read and
written over REPORT_COMPOSER_PROJECT_DATABASE_URL, a DSN with `{database}` in place of the database
name, filled with `project_<pid without hyphens>`. A project database is opened only after
guards.guard has decided membership for that pid (the callers open it inside the guarded route).

One connection per call, one transaction, closed on exit: no pool (I17.1). The first open of a database
in this process migrates it first (lock 8_190_233_707 in that database, the history re-read inside the
lock), unless the start loop already did.
"""
from __future__ import annotations

import re
import threading
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from . import migrate
from .errors import ApiError

_PID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
PLACEHOLDER = "{database}"
NO_PROJECT = "No such project."
UNAVAILABLE = "This project's reports cannot be reached just now."


def database_name(pid: str) -> str:
    """I1.8: project_<32 lowercase hex digits>; anything but a canonical uuid is refused."""
    if not isinstance(pid, str) or not _PID.match(pid):
        raise ValueError("not a project pid")
    return "project_" + pid.replace("-", "").lower()


def dsn_for(template: str, name: str) -> str:
    if not template or PLACEHOLDER not in template:
        raise ValueError("REPORT_COMPOSER_PROJECT_DATABASE_URL must contain {database}")
    return template.replace(PLACEHOLDER, name)


class ProjectDatabases:
    def __init__(self, template: str, platform_url: str) -> None:
        self.template = template or ""
        self.platform_url = platform_url
        self._migrated: set[str] = set()
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def dsn(self, pid: str) -> str:
        return dsn_for(self.template, database_name(pid))

    def exists(self, pid: str) -> bool:
        with psycopg.connect(self.platform_url) as conn:
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
        """A connect error: 404 when the database is gone (I2.5), else 503. The error text is not parsed."""
        try:
            gone = not self.exists(pid)
        except psycopg.Error:
            return ApiError(503, "unavailable", UNAVAILABLE)
        if gone:
            self.forget(pid)
            return ApiError(404, "not_found", NO_PROJECT)
        return ApiError(503, "unavailable", UNAVAILABLE)

    def _open(self, pid: str):
        try:
            dsn = self.dsn(pid)
        except ValueError:  # the template has no {database}: a configuration error, not the caller's
            raise ApiError(503, "unavailable", UNAVAILABLE) from None
        try:
            # through the module attribute: the tests' spies replace psycopg.connect
            return psycopg.connect(dsn, row_factory=dict_row)
        except psycopg.OperationalError:
            raise self._refused(pid) from None

    def _migrate_once(self, pid: str, name: str) -> None:
        if name in self._migrated:
            return
        with self._lock_for(name):
            if name in self._migrated:
                return
            conn = self._open(pid)
            try:
                with conn:
                    migrate.migrate_project(conn)
            except migrate.SchemaMissing:
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
