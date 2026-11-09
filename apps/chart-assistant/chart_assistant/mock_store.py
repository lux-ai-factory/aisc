"""The projects' mock databases: one per project and description (assistant_mock_<hex>_<digest>), made from the
description; when the description changes a new one is made and the project's older ones are dropped. The assistant's
role owns them and nothing else."""
from __future__ import annotations

import hashlib
import json
import random
import threading

import psycopg

from chart_assistant import mock
from chart_assistant.description import fixed_model

STATEMENT_TIMEOUT_MS = 5000
MAX_ROWS = 200


class MockStore:
    def __init__(self, admin_url: str):
        self.admin_url = admin_url
        self._lock = threading.Lock()

    def _url(self, name: str) -> str:
        return self.admin_url.rsplit("/", 1)[0] + "/" + name

    def _make(self, admin, name: str, description: dict, digest: str) -> None:
        """Fill the database under a building name and give it its own name only once it is filled: a fill that fails
        (or a process that dies halfway) never leaves a database that a later conversation takes as made."""
        building = f"{name}_b"
        admin.execute(f'DROP DATABASE IF EXISTS "{building}"')
        admin.execute(f'CREATE DATABASE "{building}"')
        try:
            with psycopg.connect(self._url(building), autocommit=True) as conn:
                conn.execute(mock.ddl(fixed_model()) + mock.inserts(mock.rows(description, random.Random(digest))))
            admin.execute(f'ALTER DATABASE "{building}" RENAME TO "{name}"')
        except BaseException:
            try:
                admin.execute(f'DROP DATABASE IF EXISTS "{building}"')
            except psycopg.Error:
                pass                                         # the next attempt drops it before building again
            raise

    @staticmethod
    def _drop_older(admin, prefix: str, keep: str) -> None:
        """The project's mock databases of older descriptions. One still in use by a query stays until the next
        change; a conversation still open on it is told its query failed."""
        for (datname,) in admin.execute("SELECT datname FROM pg_database").fetchall():
            if datname.startswith(prefix) and datname != keep:
                try:
                    admin.execute(f'DROP DATABASE IF EXISTS "{datname}"')
                except psycopg.Error:
                    pass

    def runner(self, pid: str, description: dict):
        digest = hashlib.sha256(json.dumps(description, sort_keys=True).encode()).hexdigest()[:12]
        name = f"assistant_mock_{pid.replace('-', '')}_{digest}"
        with self._lock:
            with psycopg.connect(self.admin_url, autocommit=True) as admin:
                exists = admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
                if not exists:
                    self._make(admin, name, description, digest)
                    self._drop_older(admin, f"assistant_mock_{pid.replace('-', '')}_", keep=name)

        def run(sql: str) -> dict:
            with psycopg.connect(self._url(name)) as conn:
                conn.execute("SET TRANSACTION READ ONLY")
                conn.execute(f"SET LOCAL statement_timeout = {STATEMENT_TIMEOUT_MS}")
                cur = conn.execute(sql)
                columns = [c.name for c in cur.description or []]
                rows = [list(r) for r in cur.fetchmany(MAX_ROWS)]
                conn.rollback()
            return {"columns": columns, "rows": json.loads(json.dumps(rows, default=str))}
        return run
