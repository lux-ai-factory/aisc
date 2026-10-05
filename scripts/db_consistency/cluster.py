"""Connections to one Postgres cluster, every one of them read-only."""

from __future__ import annotations

from dataclasses import dataclass

import psycopg

READ_ONLY = "-c default_transaction_read_only=on"


@dataclass
class Cluster:
    """A superuser conninfo (libpq keywords or URL; empty means the PG* environment) and the
    names of the databases the checks read."""

    conninfo: str = ""
    platform_db: str = "platform"
    superset_db: str = "superset"
    keycloak_db: str = "keycloak"
    realm: str = "aisc"

    def connect(self, dbname: str) -> psycopg.Connection:
        return psycopg.connect(self.conninfo, dbname=dbname, options=READ_ONLY,
                               autocommit=True, connect_timeout=10)

    def rows(self, dbname: str, sql: str, params: tuple | dict | None = None) -> list[tuple]:
        with self.connect(dbname) as conn:
            return conn.execute(sql, params).fetchall()

    def databases(self) -> list[str]:
        return [r[0] for r in self.rows(
            "postgres", "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname")]

    def exists(self, dbname: str, relation: str) -> bool:
        """Whether a table (schema.name) exists in that database."""
        return self.rows(dbname, "SELECT to_regclass(%s) IS NOT NULL", (relation,))[0][0]
